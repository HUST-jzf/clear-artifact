"""R46: a ticket service with two dedup regimes.

`--dedup keyed` honours a client-supplied key and dedups on it.
`--dedup content` ignores the key and dedups on a hash of the call arguments,
which is what a tool without an idempotency field can offer.

Two faults are injected on `attach`: `lost_return` and `late_commit`.  The
service also exposes the execution lifecycle, the effect index, an atomic
admission endpoint and fence settlement, so controllers that do not rely on a
key can still recover.
"""
import argparse
import hashlib
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


def content_hash(args):
    return hashlib.sha256(json.dumps(args, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()[:32]


class Store:
    def __init__(self, root, dedup):
        self.root = Path(root)
        self.private = self.root / 'private'
        self.private.mkdir(parents=True)
        self.dedup_mode = dedup
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
                db.execute('create table if not exists effects(id integer primary key, '
                           'op text, step text, attempt integer, allowed integer, '
                           'manifest text, ts integer, fence integer, key text, '
                           'content_key text, status text, intent text, args text)')
                db.execute('create table if not exists fences(op text primary key, '
                           'next integer default 1, finalized integer default 0)')
                db.execute('create table if not exists dedup_hits(id integer primary key, '
                           'key text, op text, step text, ts integer)')
                db.execute('create unique index if not exists effects_key on effects(key) '
                           'where key is not null')
                db.commit()
                self.connections[workflow] = db
                self.guards[workflow] = threading.Lock()
            return self.connections[workflow], self.guards[workflow]

    def workflow(self, workflow):
        with self.lock:
            return self.workflows.setdefault(
                workflow, dict(epoch=1, allowed=True, manifest=dict(MANIFEST),
                               faults=self.faults.get(workflow, {})))

    def identity(self, workflow, op, step, attempt):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('insert or ignore into ops(op, step) values(?,?)', (op, step))
            row = db.execute('select count(*) from effects where op=?', (op,)).fetchone()[0]
            db.commit()
        return row + 1 if attempt is None else attempt

    def allocate(self, workflow, op):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('begin immediate')
            row = db.execute('select next, finalized from fences where op=?', (op,)).fetchone()
            if row is None:
                db.execute('insert into fences(op, next, finalized) values(?,?,?)', (op, 1, 0))
                fence = 1
                db.execute('update fences set next=? where op=?', (2, op))
            else:
                fence = int(row[0])
                db.execute('update fences set next=? where op=?', (fence + 1, op))
            db.commit()
        return dict(fence=fence)

    def body(self, op, step, attempt, record_id, intent, args, fence, state, key=None):
        return dict(state=state, op=op, operation_id=op, step=step, record_id=record_id,
                    attempt=attempt, allowed=True, manifest=MANIFEST['version'],
                    intent=intent, args=args, generation=1, fence=fence, key=key,
                    effect_namespace='effects')

    def insert(self, db, op, step, attempt, intent, args, fence, status, key):
        content = content_hash(args)
        cur = db.execute('insert into effects(op,step,attempt,allowed,manifest,ts,fence,'
                         'key,content_key,status,intent,args) '
                         'values(?,?,?,?,?,?,?,?,?,?,?,?)',
                         (op, step, attempt, 1, MANIFEST['version'], time.time_ns(),
                          fence, key, content, status, intent,
                          json.dumps(args, sort_keys=True)))
        return cur.lastrowid, content

    def write(self, workflow, op, step, attempt, intent, args, fence, mode):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('begin immediate')
            row = db.execute('select finalized from fences where op=?', (op,)).fetchone()
            finalized = int(row[0]) if row else 0
            if fence is not None and fence <= finalized:
                db.commit()
                return 409, dict(state='stale_fence', op=op, fence=fence,
                                 finalized=finalized)
            status = 'committed' if mode == 'commit' else 'provisional'
            record_id, _ = self.insert(db, op, step, attempt, intent, args, fence, status, None)
            body = self.body(op, step, attempt, record_id, intent, args, fence, status)
            if status == 'committed':
                if fence is not None:
                    db.execute('insert or ignore into fences(op, next, finalized) '
                               'values(?,?,?)', (op, 1, 0))
                    db.execute('update fences set finalized=? where op=?', (fence, op))
                db.execute('update ops set terminal=1, receipt=? where op=?',
                           (json.dumps(body), op))
            db.commit()
        return 200, body

    def admit(self, workflow, op, step, attempt, intent, args):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('begin immediate')
            prev = db.execute('select receipt from ops where op=? and receipt is not null',
                              (op,)).fetchone()
            if prev is not None:
                body = json.loads(prev[0])
                body['deduplicated'] = True
                db.commit()
                return 200, body
            record_id, _ = self.insert(db, op, step, attempt, intent, args, None,
                                       'committed', None)
            body = self.body(op, step, attempt, record_id, intent, args, None, 'committed')
            db.execute('update ops set terminal=1, receipt=? where op=?',
                       (json.dumps(body), op))
            db.commit()
        return 200, body

    def dedup(self, workflow, op, step, attempt, intent, args, key):
        effective = content_hash(args) if self.dedup_mode == 'content' else key
        db, guard = self.guard(workflow)
        with guard:
            db.execute('begin immediate')
            prev = db.execute('select id, intent from effects where key=?',
                              (effective,)).fetchone()
            if prev is not None:
                db.execute('insert into dedup_hits(key, op, step, ts) values(?,?,?,?)',
                           (effective, op, step, time.time_ns()))
                db.execute('update ops set terminal=1 where op=?', (op,))
                db.commit()
                return 200, dict(state='deduplicated', duplicate=True, op=op, step=step,
                                 record_id=prev[0], intent=prev[1], key=effective,
                                 effect_namespace='effects')
            record_id, _ = self.insert(db, op, step, attempt, intent, args, None,
                                       'committed', effective)
            body = self.body(op, step, attempt, record_id, intent, args, None, 'committed',
                             effective)
            db.execute('update ops set terminal=1, receipt=? where op=?',
                       (json.dumps(body), op))
            db.commit()
        return 200, body

    def finalize(self, workflow, op, fence):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('begin immediate')
            exists = db.execute('select 1 from effects where op=? and status=?',
                                (op, 'committed')).fetchone() is not None
            if exists:
                db.rollback()
                return 409, dict(state='already_committed', op=op)
            row = db.execute('select finalized from fences where op=?', (op,)).fetchone()
            finalized = int(row[0]) if row else 0
            if fence is None or fence <= finalized:
                db.rollback()
                return 409, dict(state='stale_fence', op=op, fence=fence,
                                 finalized=finalized)
            target = db.execute('select id, step, attempt, intent, args from effects '
                                'where op=? and fence=? and status=?',
                                (op, fence, 'provisional')).fetchone()
            if target is None:
                db.rollback()
                return 409, dict(state='unknown_provisional', op=op, fence=fence)
            record_id, step, attempt, intent, args = target
            body = self.body(op, step, attempt, record_id, intent, json.loads(args), fence,
                             'committed')
            db.execute('update effects set status=? where id=?', ('committed', record_id))
            db.execute('update fences set finalized=? where op=?', (fence, op))
            db.execute('update ops set terminal=1, receipt=? where op=?',
                       (json.dumps(body), op))
            db.commit()
        return 200, body

    def fault_delay(self, workflow, step):
        fault = self.workflow(workflow)['faults'].get(step)
        if not fault or fault.get('fired') or fault.get('kind') != 'late_commit':
            return False
        fault['fired'] = True
        time.sleep(float(fault.get('delay', 0.9)))
        return False

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
            rows = db.execute('select id, attempt, fence, status, intent, key, content_key '
                              'from effects where op=? order by id', (op,)).fetchall()
        if not row:
            return 404, dict(error='unknown_op', op=op)
        committed = [r for r in rows if r[3] == 'committed']
        state = 'committed' if committed else 'not_committed'
        body = dict(root=op, op=op, state=state, complete=True, effect_namespace='effects',
                    rows=[dict(record_id=r[0], attempt=r[1], fence=r[2], status=r[3],
                               intent=r[4], key=r[5], content_key=r[6]) for r in rows],
                    provisional=sum(1 for r in rows if r[3] == 'provisional'))
        return 200, body

    def summary(self, workflow):
        db, guard = self.guard(workflow)
        with guard:
            rows = db.execute("select op, intent, count(*) from effects "
                              "where status='committed' group by op, intent").fetchall()
            provisional = db.execute("select count(*) from effects "
                                     "where status='provisional'").fetchone()[0]
            hits = db.execute('select count(*) from dedup_hits').fetchone()[0]
        ops = {}
        for op, intent, count in rows:
            entry = ops.setdefault(op, dict(effects=0, intents=[]))
            entry['effects'] += count
            entry['intents'].append(intent)
        return dict(ops=ops, provisional=int(provisional), deduplicated=int(hits))


class Server(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-root', required=True)
    parser.add_argument('--dedup', required=True, choices=['keyed', 'content'])
    args = parser.parse_args()
    root = Path(args.run_root).resolve()
    store = Store(root, args.dedup)

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
                return self.send(200, dict(manifest=MANIFEST, dedup=store.dedup_mode))
            if parts[:1] == ['permit'] and len(parts) == 2:
                state = store.workflow(parts[1])
                return self.send(200, dict(workflow=parts[1], epoch=state['epoch'],
                                           allowed=state['allowed']))
            if len(parts) == 5 and parts[0] == 'w' and parts[2] == 'ops' and parts[4] == 'effects':
                return self.send(*store.effects(parts[1], parts[3]))
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
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'fence':
                return self.send(200, store.allocate(parts[1], self.body()['op']))
            if len(parts) == 3 and parts[0] == 'w' and parts[2] in ('admit', 'dedup', 'write'):
                action = parts[2]
                request = self.body()
                op, step = request['op'], request['step']
                attempt = store.identity(parts[1], op, step, request.get('attempt'))
                store.fault_delay(parts[1], step)
                if action == 'admit':
                    code, body = store.admit(parts[1], op, step, attempt,
                                             request.get('intent', ''),
                                             request.get('args') or {})
                elif action == 'dedup':
                    code, body = store.dedup(parts[1], op, step, attempt,
                                             request.get('intent', ''),
                                             request.get('args') or {},
                                             request.get('key', ''))
                else:
                    code, body = store.write(parts[1], op, step, attempt,
                                             request.get('intent', ''),
                                             request.get('args') or {},
                                             request.get('fence'),
                                             request.get('mode', 'commit'))
                if store.fault_after(parts[1], step, self):
                    return
                return self.send(code, body)
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'finalize':
                request = self.body()
                return self.send(*store.finalize(parts[1], request['op'],
                                                 request.get('fence')))
            return self.send(404, dict(error='not_found'))

    server = Server(('127.0.0.1', 0), Handler)
    server.handle_error = lambda *args: None
    save(root / 'ready.json', dict(base_url='http://127.0.0.1:' + str(server.server_port),
                                   dedup=store.dedup_mode))
    try:
        server.serve_forever(poll_interval=0.001)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
