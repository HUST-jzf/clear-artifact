"""R35: the ticket service with an armed revocation inside the write path."""
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
        self.connections = {}
        self.guards = {}
        self.faults = json.loads((self.root / 'faults.json').read_text(encoding='utf-8'))

    def guard(self, workflow):
        with self.lock:
            if workflow not in self.connections:
                db = sqlite3.connect(self.private / (workflow + '.sqlite'),
                                     check_same_thread=False)
                db.execute('pragma journal_mode=wal')
                db.execute('pragma busy_timeout=5000')
                db.execute('create table if not exists ops(op text primary key, step text, '
                           'terminal integer default 0, receipt text)')
                db.execute('create table if not exists effects(id integer primary key, op text, '
                           'step text, attempt integer, allowed integer, manifest text, ts integer)')
                db.commit()
                self.connections[workflow] = db
                self.guards[workflow] = threading.Lock()
            return self.connections[workflow], self.guards[workflow]

    def workflow(self, workflow):
        with self.lock:
            return self.workflows.setdefault(
                workflow, dict(epoch=1, allowed=True, armed=False,
                               faults=self.faults.get(workflow, {})))

    def revoke_if_armed(self, workflow):
        state = self.workflow(workflow)
        if state.get('armed'):
            state['armed'] = False
            state['allowed'] = False
            state['epoch'] += 1

    def identity(self, workflow, op, step, attempt):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('insert or ignore into ops(op, step) values(?,?)', (op, step))
            row = db.execute('select count(*) from effects where op=?', (op,)).fetchone()[0]
            db.commit()
        return row + 1 if attempt is None else attempt

    def body(self, op, step, attempt, record_id, allowed, intent):
        return dict(state='committed', op=op, operation_id=op, step=step,
                    record_id=record_id, attempt=attempt, allowed=bool(allowed),
                    manifest=MANIFEST['version'], intent=intent, generation=1,
                    effect_namespace='effects')

    def append(self, workflow, op, step, attempt, permit_epoch, intent):
        db, guard = self.guard(workflow)
        with guard:
            self.revoke_if_armed(workflow)
            state = self.workflow(workflow)
            allowed = int(permit_epoch == state['epoch'] and state['allowed'])
            cur = db.execute('insert into effects(op,step,attempt,allowed,manifest,ts) '
                             'values(?,?,?,?,?,?)',
                             (op, step, attempt, allowed, MANIFEST['version'], time.time_ns()))
            record_id = cur.lastrowid
            body = self.body(op, step, attempt, record_id, allowed, intent)
            db.execute('update ops set terminal=1, receipt=? where op=?',
                       (json.dumps(body), op))
            db.commit()
        return 200, body

    def admit(self, workflow, op, step, attempt, permit_epoch, intent):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('begin immediate')
            self.revoke_if_armed(workflow)
            state = self.workflow(workflow)
            allowed = permit_epoch == state['epoch'] and state['allowed']
            exists = db.execute('select 1 from effects where op=? limit 1',
                                (op,)).fetchone() is not None
            if not allowed:
                db.rollback()
                return 409, dict(state='stale_qualification', op=op, step=step,
                                 allowed=False, epoch=state['epoch'])
            if exists:
                db.rollback()
                return 409, dict(state='duplicate_effect', op=op, step=step,
                                 duplicate=True)
            cur = db.execute('insert into effects(op,step,attempt,allowed,manifest,ts) '
                             'values(?,?,?,?,?,?)',
                             (op, step, attempt, 1, MANIFEST['version'], time.time_ns()))
            record_id = cur.lastrowid
            body = self.body(op, step, attempt, record_id, 1, intent)
            db.execute('update ops set terminal=1, receipt=? where op=?',
                       (json.dumps(body), op))
            db.commit()
        return 200, body

    def close_connection(self, handler):
        handler.close_connection = True
        try:
            handler.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        handler.connection.close()
        handler.wfile = io.BytesIO()

    def fault_before(self, workflow, op, step, handler):
        fault = self.workflow(workflow)['faults'].get(step)
        if not fault or fault.get('fired') or fault.get('kind') != 'lost_before_commit':
            return False
        fault['fired'] = True
        db, guard = self.guard(workflow)
        with guard:
            db.execute('update ops set terminal=1, receipt=NULL where op=?', (op,))
            db.commit()
        self.close_connection(handler)
        return True

    def fault_after(self, workflow, step, handler):
        fault = self.workflow(workflow)['faults'].get(step)
        if not fault or fault.get('fired'):
            return False
        fault['fired'] = True
        if fault['kind'] == 'lost_return':
            self.close_connection(handler)
            return True
        return False

    def lifecycle(self, workflow, op):
        db, guard = self.guard(workflow)
        with guard:
            row = db.execute('select step, terminal, receipt from ops where op=?',
                             (op,)).fetchone()
        if not row:
            return 404, dict(error='unknown_op', op=op)
        receipt = json.loads(row[2]) if row[2] else None
        state = 'committed' if receipt else ('not_committed' if not row[1] else 'unknown')
        return 200, dict(root=op, op=op, step=row[0], terminal=bool(row[1]),
                         receipt=receipt, state=state, complete=True,
                         registration_complete=True, effect_namespace='effects',
                         members=[dict(handle=op, parent=None, terminal=bool(row[1]),
                                       receipt=receipt)])

    def effects(self, workflow, op):
        db, guard = self.guard(workflow)
        with guard:
            row = db.execute('select terminal, receipt from ops where op=?', (op,)).fetchone()
            rows = db.execute('select id, attempt, allowed from effects where op=? order by id',
                              (op,)).fetchall()
        if not row:
            return 404, dict(error='unknown_op', op=op)
        body = json.loads(row[1]) if row[1] else dict(
            root=op, op=op, state='not_committed', complete=True,
            effect_namespace='effects')
        body['root'] = op
        body['rows'] = [dict(record_id=r[0], attempt=r[1], allowed=bool(r[2])) for r in rows]
        return 200, body

    def summary(self, workflow):
        db, guard = self.guard(workflow)
        with guard:
            rows = db.execute('select step, count(*), sum(allowed) '
                              'from effects group by step').fetchall()
        return {step: dict(rows=count, stale=count - (allowed or 0))
                for step, count, allowed in rows}


class Server(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True


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

        def parts(self):
            return [part for part in self.path.split('?')[0].strip('/').split('/') if part]

        def do_GET(self):
            parts = self.parts()
            if parts == ['manifest']:
                return self.send(200, dict(manifest=MANIFEST))
            if parts[:1] == ['permit'] and len(parts) == 2:
                state = store.workflow(parts[1])
                return self.send(200, dict(workflow=parts[1], epoch=state['epoch'],
                                           allowed=state['allowed']))
            if len(parts) == 5 and parts[0] == 'w' and parts[2] == 'ops' and parts[4] == 'effects':
                return self.send(*store.effects(parts[1], parts[3]))
            if len(parts) == 4 and parts[0] == 'w' and parts[2] == 'ops':
                return self.send(*store.lifecycle(parts[1], parts[3]))
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'state':
                return self.send(200, dict(workflow=parts[1],
                                           steps=store.summary(parts[1])))
            return self.send(404, dict(error='not_found'))

        def do_POST(self):
            parts = self.parts()
            if parts == ['control', 'stop']:
                save(root / 'private' / 'stats.json',
                     {wf: store.summary(wf) for wf in store.workflows})
                self.send(200, dict(stopped=True))
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'arm_revoke':
                state = store.workflow(parts[1])
                state['armed'] = True
                return self.send(200, dict(workflow=parts[1], armed=True))
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'admit':
                request = self.body()
                op, step = request['op'], request['step']
                attempt = store.identity(parts[1], op, step, request.get('attempt'))
                return self.send(*store.admit(parts[1], op, step, attempt,
                                              int(request.get('permit_epoch', 1)),
                                              request.get('intent', '')))
            if len(parts) != 3 or parts[0] != 'w':
                return self.send(404, dict(error='not_found'))
            workflow, step = parts[1], parts[2]
            if step not in STEPS:
                return self.send(404, dict(error='unknown_step'))
            request = self.body()
            op = request.get('op') or f"{workflow}:{step}"
            attempt = store.identity(workflow, op, step, request.get('attempt'))
            if store.fault_before(workflow, op, step, self):
                return
            return self.send(*store.append(workflow, op, step, attempt,
                                           int(request.get('permit_epoch', 1)),
                                           request.get('intent', '')))

    server = Server(('127.0.0.1', 0), Handler)
    server.handle_error = lambda *args: None
    save(root / 'ready.json', dict(base_url='http://127.0.0.1:' + str(server.server_port)))
    try:
        server.serve_forever(poll_interval=0.001)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
