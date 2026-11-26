"""R15: a non-idempotent third-party ticket service over real HTTP + SQLite.

The service knows nothing about CLEAR. It exposes five append-only operations and
records who wrote with which permit epoch. A fault file maps a workflow id to one
scripted fault, applied after the named step commits.
"""
import argparse
import io
import json
import socket
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
MANIFEST = dict(version='ticket-svc-2026.10-v1', sha='5b1f7c0d')


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8')


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.private = self.root / 'private'
        self.private.mkdir(parents=True)
        self.lock = threading.RLock()
        self.workflows = {}
        self.faults = json.loads((self.root / 'faults.json').read_text(encoding='utf-8'))
        self.idempotency = (self.root / 'idempotency').read_text().strip() == 'on'
        self.schema = set()

    def db(self, workflow):
        path = self.private / (workflow + '.sqlite')
        with sqlite3.connect(path) as db:
            if workflow not in self.schema:
                db.execute('create table if not exists ops(op text primary key, step text, '
                           'terminal integer default 0, receipt text)')
                db.execute('create table if not exists effects(id integer primary key, op text, '
                           'step text, attempt integer, allowed integer, manifest text, ts integer)')
                db.execute('create table if not exists idem(key text primary key, response text)')
                self.schema.add(workflow)
        return path

    def workflow(self, workflow):
        with self.lock:
            return self.workflows.setdefault(
                workflow, dict(epoch=1, allowed=True, faults=self.faults.get(workflow, {})))

    def identity(self, workflow, op, step, attempt):
        with sqlite3.connect(self.db(workflow)) as db:
            db.execute('insert or ignore into ops(op, step) values(?,?)', (op, step))
            row = db.execute('select count(*) from effects where op=?', (op,)).fetchone()[0]
        return row + 1 if attempt is None else attempt

    def commit(self, workflow, op, step, attempt, permit_epoch, key, intent):
        state = self.workflow(workflow)
        allowed = int(permit_epoch == state['epoch'] and state['allowed'])
        with sqlite3.connect(self.db(workflow)) as db:
            if key and self.idempotency:
                cached = db.execute('select response from idem where key=?', (key,)).fetchone()
                if cached:
                    body = json.loads(cached[0])
                    body['cached'] = True
                    return body
            cur = db.execute('insert into effects(op,step,attempt,allowed,manifest,ts) '
                             'values(?,?,?,?,?,?)',
                             (op, step, attempt, allowed, MANIFEST['version'], time.time_ns()))
            record_id = cur.lastrowid
            body = dict(state='committed', op=op, operation_id=op, step=step,
                        record_id=record_id, attempt=attempt, allowed=bool(allowed),
                        manifest=MANIFEST['version'], intent=intent, generation=1,
                        effect_namespace='effects')
            db.execute('update ops set terminal=1, receipt=? where op=?',
                       (json.dumps(body), op))
            if key and self.idempotency:
                db.execute('insert or replace into idem(key,response) values(?,?)',
                           (key, json.dumps(body)))
        return body

    def fault_after(self, workflow, step, handler):
        fault = self.workflow(workflow)['faults'].get(step)
        if not fault or fault.get('fired'):
            return False
        fault['fired'] = True
        kind = fault['kind']
        if kind == 'lost_return':
            handler.close_connection = True
            try:
                handler.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            handler.connection.close()
            handler.wfile = io.BytesIO()
            return True
        if kind == 'late_commit':
            time.sleep(float(fault.get('delay', 0.4)))
            return False
        if kind in ('revoke_after_reserve', 'revoke_after_commit'):
            state = self.workflow(workflow)
            state['allowed'] = False
            state['epoch'] += 1
            return False
        return False

    def status(self, workflow, op):
        with sqlite3.connect(self.db(workflow)) as db:
            row = db.execute('select step, terminal, receipt from ops where op=?',
                             (op,)).fetchone()
            rows = db.execute('select id, attempt, allowed, manifest from effects '
                              'where op=? order by id', (op,)).fetchall()
        if not row:
            return dict(error='unknown_op', op=op)
        receipt = json.loads(row[2]) if row[2] else None
        state = 'committed' if rows else ('not_committed' if row[1] else 'unknown')
        return dict(root=op, op=op, step=row[0], terminal=bool(row[1]), receipt=receipt,
                    state=state, complete=True, registration_complete=True,
                    effect_namespace='effects',
                    members=[dict(handle=op, parent=None, terminal=bool(row[1]),
                                  receipt=receipt)],
                    rows=[dict(record_id=r[0], attempt=r[1], allowed=bool(r[2]),
                               manifest=r[3]) for r in rows])

    def summary(self, workflow):
        with sqlite3.connect(self.db(workflow)) as db:
            rows = db.execute('select step, count(*), sum(allowed), min(manifest) '
                              'from effects group by step').fetchall()
        return {step: dict(rows=count, stale=count - (allowed or 0))
                for step, count, allowed, manifest in rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-root', required=True)
    args = parser.parse_args()
    root = Path(args.run_root).resolve()
    store = Store(root)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def send(self, code, body):
            data = json.dumps(body, separators=(',', ':')).encode()
            self.send_response(code)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(data)

        def body(self):
            length = int(self.headers.get('Content-Length', 0))
            return json.loads(self.rfile.read(length)) if length else {}

        def path_parts(self):
            return [part for part in self.path.split('?')[0].strip('/').split('/') if part]

        def do_GET(self):
            parts = self.path_parts()
            if parts == ['manifest']:
                return self.send(200, dict(manifest=MANIFEST))
            if parts[:1] == ['permit'] and len(parts) == 2:
                state = store.workflow(parts[1])
                return self.send(200, dict(workflow=parts[1], epoch=state['epoch'],
                                           allowed=state['allowed']))
            if len(parts) == 4 and parts[0] == 'w' and parts[2] == 'ops':
                return self.send(200, store.status(parts[1], parts[3]))
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'state':
                return self.send(200, dict(workflow=parts[1],
                                           steps=store.summary(parts[1])))
            return self.send(404, dict(error='not_found'))

        def do_POST(self):
            parts = self.path_parts()
            if parts == ['control', 'stop']:
                save(root / 'private' / 'stats.json',
                     {wf: store.summary(wf) for wf in store.workflows})
                save(root / 'private' / 'workflows.json', store.workflows)
                self.send(200, dict(stopped=True))
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'reauthorize':
                state = store.workflow(parts[1])
                state['allowed'] = True
                state['epoch'] += 1
                return self.send(200, dict(workflow=parts[1], epoch=state['epoch'],
                                           allowed=True))
            if len(parts) != 3 or parts[0] != 'w':
                return self.send(404, dict(error='not_found'))
            workflow, step = parts[1], parts[2]
            if step not in STEPS:
                return self.send(404, dict(error='unknown_step'))
            request = self.body()
            op = request.get('op') or f"{workflow}:{step}"
            attempt = store.identity(workflow, op, step, request.get('attempt'))
            body = store.commit(workflow, op, step, attempt,
                                int(request.get('permit_epoch', 1)),
                                self.headers.get('Idempotency-Key'),
                                request.get('intent', ''))
            if store.fault_after(workflow, step, self):
                return
            try:
                self.send(200, body)
            except OSError:
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.handle_error = lambda *args: None
    save(root / 'ready.json', dict(base_url='http://127.0.0.1:' + str(server.server_port)))
    try:
        server.serve_forever(poll_interval=0.001)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
