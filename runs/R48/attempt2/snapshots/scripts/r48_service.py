"""R48: single-step executor with cancel/stop and optional closure evidence.

`--stop on` makes the executor honour a cancel that arrives before the effect is
written; `--stop off` finishes the request anyway.  `--closure on` exposes the
terminal flag and receipt of the original call; `--closure off` returns 501.
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

MANIFEST = dict(version='ticket-svc-2026.10-v1', sha='5b1f7c0d')


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8')


class Store:
    def __init__(self, root, stop, closure):
        self.root = Path(root)
        self.private = self.root / 'private'
        self.private.mkdir(parents=True)
        self.stop = stop
        self.closure = closure
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
                db.execute('create table if not exists ops(op text primary key, '
                           'terminal integer default 0, receipt text, state text)')
                db.execute('create table if not exists effects(id integer primary key, '
                           'op text, attempt integer, ts integer)')
                db.commit()
                self.connections[workflow] = db
                self.guards[workflow] = threading.Lock()
            return self.connections[workflow], self.guards[workflow]

    def workflow(self, workflow):
        with self.lock:
            return self.workflows.setdefault(
                workflow, dict(faults=self.faults.get(workflow, {}), cancelled=set()))

    def fault_delay(self, workflow, step):
        fault = self.workflow(workflow)['faults'].get(step)
        if not fault or fault.get('fired') or fault.get('kind') != 'late_commit':
            return
        fault['fired'] = True
        time.sleep(float(fault.get('delay', 0.9)))

    def fault_after(self, workflow, step, handler):
        fault = self.workflow(workflow)['faults'].get(step)
        if not fault or fault.get('fired'):
            return False
        if fault.get('kind') == 'lost_return':
            fault['fired'] = True
            handler.close_connection = True
            try:
                handler.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            handler.connection.close()
            handler.wfile = io.BytesIO()
            return True
        return False

    def attach(self, workflow, op, attempt):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('begin immediate')
            cancelled = (op, attempt) in self.workflow(workflow)['cancelled']
            if self.stop and cancelled:
                db.execute('insert or replace into ops(op, terminal, receipt, state) '
                           'values(?,?,?,?)', (op, 1, None, 'cancelled'))
                db.commit()
                return 409, dict(state='cancelled', op=op)
            cur = db.execute('insert into effects(op, attempt, ts) values(?,?,?)',
                             (op, attempt, time.time_ns()))
            body = dict(state='committed', op=op, attempt=attempt,
                        record_id=cur.lastrowid, manifest=MANIFEST['version'])
            db.execute('insert or replace into ops(op, terminal, receipt, state) '
                       'values(?,?,?,?)', (op, 1, json.dumps(body), 'committed'))
            db.commit()
        return 200, body

    def cancel(self, workflow, op, attempt=1):
        with self.lock:
            self.workflow(workflow)['cancelled'].add((op, attempt))
        return 200, dict(state='cancel_requested', op=op, attempt=attempt)

    def lifecycle(self, workflow, op):
        if not self.closure:
            return 501, dict(error='closure_unavailable', op=op)
        db, guard = self.guard(workflow)
        with guard:
            row = db.execute('select terminal, receipt, state from ops where op=?',
                             (op,)).fetchone()
        if not row:
            return 200, dict(op=op, terminal=False, receipt=None, state='pending')
        receipt = json.loads(row[1]) if row[1] else None
        return 200, dict(op=op, terminal=bool(row[0]), receipt=receipt,
                         state=row[2] or 'pending')

    def summary(self, workflow):
        db, guard = self.guard(workflow)
        with guard:
            effects = db.execute('select count(*) from effects').fetchone()[0]
            row = db.execute('select terminal, state from ops limit 1').fetchone()
        return dict(effects=int(effects), terminal=bool(row[0]) if row else False,
                    state=row[1] if row else 'pending')


class Server(ThreadingHTTPServer):
    request_queue_size = 64
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-root', required=True)
    parser.add_argument('--stop', required=True, choices=['on', 'off'])
    parser.add_argument('--closure', required=True, choices=['on', 'off'])
    args = parser.parse_args()
    root = Path(args.run_root).resolve()
    store = Store(root, args.stop == 'on', args.closure == 'on')

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
                return self.send(200, dict(manifest=MANIFEST, stop=args.stop,
                                           closure=args.closure))
            if len(parts) == 4 and parts[0] == 'w' and parts[2] == 'ops':
                return self.send(*store.lifecycle(parts[1], parts[3]))
            return self.send(404, dict(error='not_found'))

        def do_POST(self):
            parts = self.parts()
            if parts == ['control', 'stop']:
                save(root / 'private' / 'stats.json',
                     {wf: store.summary(wf) for wf in store.workflows})
                self.send(200, dict(stopped=True))
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'cancel':
                request = self.body()
                return self.send(*store.cancel(parts[1], request['op'],
                                               int(request.get('attempt', 1))))
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'attach':
                request = self.body()
                op = request['op']
                store.fault_delay(parts[1], 'attach')
                code, body = store.attach(parts[1], op, int(request.get('attempt', 1)))
                if store.fault_after(parts[1], 'attach', self):
                    return
                return self.send(code, body)
            return self.send(404, dict(error='not_found'))

    server = Server(('127.0.0.1', 0), Handler)
    server.handle_error = lambda *args: None
    save(root / 'ready.json', dict(base_url='http://127.0.0.1:' + str(server.server_port),
                                   stop=args.stop, closure=args.closure))
    try:
        server.serve_forever(poll_interval=0.001)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
