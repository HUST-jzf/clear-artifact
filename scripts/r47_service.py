"""R47: a seat service with intent-scoped effects and three disposal paths.

Effects carry an intent and a state (`active`, `compensated`, `transferred`).
Each operation has a binding epoch; `transfer` bumps the old binding's epoch in
the same transaction that writes the new intent's effect, so an in-flight write
from the old binding is rejected.  `compensate` only marks effects it can see.
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

MANIFEST = dict(version='seat-svc-2026.10-v1', sha='7a1c9e42')


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
                db.execute('create table if not exists effects(id integer primary key, '
                           'op text, intent text, seat text, kind text, state text, '
                           'ref integer, ts integer)')
                db.execute('create table if not exists bindings(op text primary key, '
                           'epoch integer default 1)')
                db.execute('create table if not exists mutations(id integer primary key, '
                           'kind text, op text, ts integer)')
                db.commit()
                self.connections[workflow] = db
                self.guards[workflow] = threading.Lock()
            return self.connections[workflow], self.guards[workflow]

    def workflow(self, workflow):
        with self.lock:
            return self.workflows.setdefault(
                workflow, dict(faults=self.faults.get(workflow, {})))

    def epoch(self, db, op):
        row = db.execute('select epoch from bindings where op=?', (op,)).fetchone()
        return int(row[0]) if row else 1

    def log(self, db, kind, op):
        db.execute('insert into mutations(kind, op, ts) values(?,?,?)',
                   (kind, op, time.time_ns()))

    def write(self, workflow, op, intent, seat, epoch):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('begin immediate')
            current = self.epoch(db, op)
            if epoch < current:
                db.commit()
                return 409, dict(state='stale_binding', op=op, epoch=epoch,
                                 current=current)
            cur = db.execute('insert into effects(op,intent,seat,kind,state,ref,ts) '
                             'values(?,?,?,?,?,?,?)',
                             (op, intent, seat, 'effect', 'active', None, time.time_ns()))
            self.log(db, 'write', op)
            db.commit()
        return 200, dict(state='committed', op=op, effect_id=cur.lastrowid,
                         intent=intent, seat=seat, epoch=epoch)

    def compensate(self, workflow, op, intent):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('begin immediate')
            rows = db.execute("select id from effects where op=? and intent=? "
                              "and kind='effect' and state='active'",
                              (op, intent)).fetchall()
            for (effect_id,) in rows:
                db.execute("update effects set state='compensated' where id=?",
                           (effect_id,))
                db.execute('insert into effects(op,intent,seat,kind,state,ref,ts) '
                           'values(?,?,?,?,?,?,?)',
                           (op, intent, '', 'compensation', 'done', effect_id,
                            time.time_ns()))
            self.log(db, 'compensate', op)
            db.commit()
        return 200, dict(state='compensated', op=op, compensated=len(rows))

    def transfer(self, workflow, from_op, from_intent, to_op, to_intent, seat):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('begin immediate')
            current = self.epoch(db, from_op)
            db.execute('insert or ignore into bindings(op, epoch) values(?,?)',
                       (from_op, current))
            db.execute('update bindings set epoch=? where op=?', (current + 1, from_op))
            rows = db.execute("select id from effects where op=? and intent=? "
                              "and kind='effect' and state='active'",
                              (from_op, from_intent)).fetchall()
            for (effect_id,) in rows:
                db.execute("update effects set state='transferred' where id=?",
                           (effect_id,))
            cur = db.execute('insert into effects(op,intent,seat,kind,state,ref,ts) '
                             'values(?,?,?,?,?,?,?)',
                             (to_op, to_intent, seat, 'effect', 'active', None,
                              time.time_ns()))
            self.log(db, 'transfer', from_op)
            db.commit()
        return 200, dict(state='transferred', from_op=from_op, to_op=to_op,
                         transferred=len(rows), effect_id=cur.lastrowid,
                         epoch=current + 1)

    def effects(self, workflow, op):
        db, guard = self.guard(workflow)
        with guard:
            rows = db.execute('select id, op, intent, seat, kind, state, ref '
                              'from effects where op=? order by id', (op,)).fetchall()
            epoch = self.epoch(db, op)
        return 200, dict(op=op, epoch=epoch,
                         effects=[dict(id=r[0], op=r[1], intent=r[2], seat=r[3],
                                       kind=r[4], state=r[5], ref=r[6]) for r in rows])

    def summary(self, workflow):
        db, guard = self.guard(workflow)
        with guard:
            rows = db.execute('select op, intent, seat, kind, state from effects '
                              'order by id').fetchall()
            mutations = db.execute('select count(*) from mutations').fetchone()[0]
            epochs = dict(db.execute('select op, epoch from bindings').fetchall())
        return dict(effects=[dict(op=r[0], intent=r[1], seat=r[2], kind=r[3], state=r[4])
                             for r in rows],
                    mutations=int(mutations),
                    epochs={op: int(value) for op, value in epochs.items()})

    def fault(self, workflow, key):
        return self.workflow(workflow)['faults'].get(key) or {}

    def fault_delay(self, workflow, key):
        fault = self.fault(workflow, key)
        if not fault or fault.get('fired') or fault.get('kind') != 'late_commit':
            return False
        fault['fired'] = True
        time.sleep(float(fault.get('delay', 0.9)))
        return False

    def fault_before(self, workflow, key, handler):
        fault = self.fault(workflow, key)
        if not fault or fault.get('fired') or fault.get('kind') != 'lost_before_commit':
            return False
        fault['fired'] = True
        self.close(handler)
        return True

    def fault_after(self, workflow, key, handler):
        fault = self.fault(workflow, key)
        if not fault or fault.get('fired'):
            return False
        if fault.get('kind') == 'lost_return':
            fault['fired'] = True
            self.close(handler)
            return True
        return False

    def close(self, handler):
        handler.close_connection = True
        try:
            handler.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        handler.connection.close()
        handler.wfile = io.BytesIO()


class Server(ThreadingHTTPServer):
    request_queue_size = 64
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
            if len(parts) == 5 and parts[0] == 'w' and parts[2] == 'ops' and parts[4] == 'effects':
                return self.send(*store.effects(parts[1], parts[3]))
            return self.send(404, dict(error='not_found'))

        def do_POST(self):
            parts = self.parts()
            if parts == ['control', 'stop']:
                save(root / 'private' / 'stats.json',
                     {wf: store.summary(wf) for wf in store.workflows})
                self.send(200, dict(stopped=True))
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if len(parts) == 3 and parts[0] == 'w' and parts[2] in ('write', 'compensate',
                                                                   'transfer'):
                action = parts[2]
                request = self.body()
                key = request.get('fault_key', '')
                if store.fault_before(parts[1], key, self):
                    return
                store.fault_delay(parts[1], key)
                if action == 'write':
                    code, body = store.write(parts[1], request['op'], request['intent'],
                                             request['seat'], int(request.get('epoch', 1)))
                elif action == 'compensate':
                    code, body = store.compensate(parts[1], request['op'],
                                                  request['intent'])
                else:
                    code, body = store.transfer(parts[1], request['from_op'],
                                                request['from_intent'],
                                                request['to_op'], request['to_intent'],
                                                request['seat'])
                if store.fault_after(parts[1], key, self):
                    return
                return self.send(code, body)
            return self.send(404, dict(error='not_found'))

    server = Server(('127.0.0.1', 0), Handler)
    server.handle_error = lambda *args: None
    save(root / 'ready.json', dict(base_url='http://127.0.0.1:' + str(server.server_port)))
    try:
        server.serve_forever(poll_interval=0.001)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
