"""R44: one service skeleton, two settlement capabilities.

`--capability fenced` exposes fence / provisional write / finalize / abort
(CLEAR's L2' contract).  `--capability dedup` exposes a single atomic
insert-or-return keyed by a client-supplied idempotency key (the baseline).

Both modes share the workflow store, the permit/manifest endpoints and the
same three fault injections (`late_effect`, `lost_before_commit`,
`lost_return`), so the comparison differs only in the settlement mechanism.
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
    def __init__(self, root, capability):
        self.root = Path(root)
        self.private = self.root / 'private'
        self.private.mkdir(parents=True)
        self.capability = capability
        self.lock = threading.RLock()
        self.workflows = {}
        self.connections = {}
        self.guards = {}
        faults = json.loads((self.root / 'faults.json').read_text(encoding='utf-8'))
        self.faults = faults
        self.closure = (self.root / 'closure').read_text().strip()

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
                           'step text, attempt integer, allowed integer, manifest text, '
                           'ts integer, fence integer, key text, status text, intent text)')
                db.execute('create table if not exists rejects(id integer primary key, '
                           'op text, fence integer, reason text, ts integer)')
                db.execute('create table if not exists dedup_hits(id integer primary key, '
                           'key text, op text, step text, ts integer)')
                if self.capability == 'fenced':
                    db.execute('create table if not exists fences(op text primary key, '
                               'next integer default 1, finalized integer default 0)')
                db.execute('create unique index if not exists effects_key on effects(key) '
                           'where key is not null')
                db.commit()
                self.connections[workflow] = db
                self.guards[workflow] = threading.Lock()
            return self.connections[workflow], self.guards[workflow]

    def workflow(self, workflow):
        with self.lock:
            return self.workflows.setdefault(
                workflow, dict(epoch=1, allowed=True, faults=self.faults.get(workflow, {})))

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

    def body(self, op, step, attempt, record_id, allowed, intent, fence, state, key=None):
        return dict(state=state, op=op, operation_id=op, step=step, record_id=record_id,
                    attempt=attempt, allowed=bool(allowed), manifest=MANIFEST['version'],
                    intent=intent, generation=1, fence=fence, key=key,
                    effect_namespace='effects')

    def reject(self, db, op, fence, reason):
        db.execute('insert into rejects(op, fence, reason, ts) values(?,?,?,?)',
                   (op, fence, reason, time.time_ns()))

    def write(self, workflow, op, step, attempt, permit_epoch, intent, fence, mode):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('begin immediate')
            state = self.workflow(workflow)
            allowed = int(permit_epoch == state['epoch'] and state['allowed'])
            row = db.execute('select finalized from fences where op=?', (op,)).fetchone()
            finalized = int(row[0]) if row else 0
            if fence is not None and fence <= finalized:
                self.reject(db, op, fence, 'stale_fence')
                db.commit()
                return 409, dict(state='stale_fence', op=op, fence=fence,
                                 finalized=finalized)
            status = 'committed' if mode == 'commit' else 'provisional'
            cur = db.execute('insert into effects(op,step,attempt,allowed,manifest,ts,'
                             'fence,status,intent) values(?,?,?,?,?,?,?,?,?)',
                             (op, step, attempt, allowed, MANIFEST['version'],
                              time.time_ns(), fence, status, intent))
            record_id = cur.lastrowid
            body = self.body(op, step, attempt, record_id, allowed, intent, fence, status)
            if status == 'committed':
                if fence is not None:
                    db.execute('insert or ignore into fences(op, next, finalized) '
                               'values(?,?,?)', (op, 1, 0))
                    db.execute('update fences set finalized=? where op=?', (fence, op))
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
            target = db.execute('select id, step, attempt, allowed, intent from effects '
                                'where op=? and fence=? and status=?',
                                (op, fence, 'provisional')).fetchone()
            if target is None:
                db.rollback()
                return 409, dict(state='unknown_provisional', op=op, fence=fence)
            record_id, step, attempt, allowed, intent = target
            body = self.body(op, step, attempt, record_id, allowed, intent, fence, 'committed')
            db.execute('update effects set status=? where id=?', ('committed', record_id))
            db.execute('update fences set finalized=? where op=?', (fence, op))
            db.execute('update ops set terminal=1, receipt=? where op=?',
                       (json.dumps(body), op))
            db.commit()
        return 200, body

    def abort(self, workflow, op, fence):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('delete from effects where op=? and fence=? and status=?',
                       (op, fence, 'provisional'))
            db.commit()
        return 200, dict(state='aborted', op=op, fence=fence)

    def dedup(self, workflow, op, step, attempt, permit_epoch, intent, key):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('begin immediate')
            state = self.workflow(workflow)
            allowed = int(permit_epoch == state['epoch'] and state['allowed'])
            prev = db.execute('select id, attempt, allowed, intent from effects where key=?',
                              (key,)).fetchone()
            if prev is not None:
                db.execute('insert into dedup_hits(key, op, step, ts) values(?,?,?,?)',
                           (key, op, step, time.time_ns()))
                db.execute('update ops set terminal=1 where op=?', (op,))
                db.commit()
                return 200, dict(state='deduplicated', duplicate=True, op=op, step=step,
                                 record_id=prev[0], intent=prev[3], key=key,
                                 effect_namespace='effects')
            cur = db.execute('insert into effects(op,step,attempt,allowed,manifest,ts,'
                             'status,intent,key) values(?,?,?,?,?,?,?,?,?)',
                             (op, step, attempt, allowed, MANIFEST['version'],
                              time.time_ns(), 'committed', intent, key))
            body = self.body(op, step, attempt, cur.lastrowid, allowed, intent, None,
                             'committed', key)
            db.execute('update ops set terminal=1, receipt=? where op=?',
                       (json.dumps(body), op))
            db.commit()
        return 200, body

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

    def fault_delay(self, workflow, step):
        fault = self.workflow(workflow)['faults'].get(step)
        if not fault or fault.get('fired') or fault.get('kind') != 'late_effect':
            return False
        fault['fired'] = True
        time.sleep(float(fault.get('delay', 1.0)))
        return False

    def fault_after(self, workflow, step, handler):
        fault = self.workflow(workflow)['faults'].get(step)
        if not fault or fault.get('fired'):
            return False
        fault['fired'] = True
        if fault['kind'] == 'lost_return':
            self.close_connection(handler)
            return True
        return False

    def close_connection(self, handler):
        handler.close_connection = True
        try:
            handler.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        handler.connection.close()
        handler.wfile = io.BytesIO()

    def lifecycle(self, workflow, op):
        if self.closure == 'absent':
            return 501, dict(error='lifecycle_unavailable', op=op)
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
            rows = db.execute('select id, attempt, allowed, fence, status, intent, key '
                              'from effects where op=? order by id', (op,)).fetchall()
        if not row:
            return 404, dict(error='unknown_op', op=op)
        committed = [r for r in rows if r[4] == 'committed']
        state = 'committed' if committed else 'not_committed'
        body = dict(root=op, op=op, state=state, complete=True, effect_namespace='effects',
                    rows=[dict(record_id=r[0], attempt=r[1], allowed=bool(r[2]),
                               fence=r[3], status=r[4], intent=r[5], key=r[6])
                          for r in rows],
                    provisional=sum(1 for r in rows if r[4] == 'provisional'))
        return 200, body

    def summary(self, workflow):
        db, guard = self.guard(workflow)
        with guard:
            rows = db.execute('select step, count(*), sum(allowed), '
                              'sum(case when status=? then 1 else 0 end) '
                              'from effects group by step', ('committed',)).fetchall()
            hits = db.execute('select step, count(*) from dedup_hits group by step').fetchall()
            intents = db.execute('select step, intent from effects where status=? order by id',
                                 ('committed',)).fetchall()
            rejected = db.execute('select count(*) from rejects').fetchone()[0]
        hit_map = {step: count for step, count in hits}
        intent_map = {}
        for step, intent in intents:
            intent_map.setdefault(step, []).append(intent)
        return dict(steps={step: dict(rows=count, stale=count - (allowed or 0),
                                      committed=committed or 0, provisional=0,
                                      duplicates=hit_map.get(step, 0),
                                      intents=intent_map.get(step, []))
                           for step, count, allowed, committed in rows},
                    rejected=int(rejected))


class Server(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-root', required=True)
    parser.add_argument('--capability', required=True, choices=['fenced', 'dedup'])
    args = parser.parse_args()
    root = Path(args.run_root).resolve()
    store = Store(root, args.capability)

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
                return self.send(200, dict(manifest=MANIFEST,
                                           capability=store.capability))
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
                                           steps=store.summary(parts[1])['steps']))
            return self.send(404, dict(error='not_found'))

        def do_POST(self):
            parts = self.parts()
            if parts == ['control', 'stop']:
                save(root / 'private' / 'stats.json',
                     {wf: store.summary(wf) for wf in store.workflows})
                self.send(200, dict(stopped=True))
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if store.capability == 'fenced' and len(parts) == 3 \
                    and parts[0] == 'w' and parts[2] == 'fence':
                return self.send(200, store.allocate(parts[1], self.body()['op']))
            if store.capability == 'dedup' and len(parts) == 3 \
                    and parts[0] == 'w' and parts[2] == 'dedup':
                request = self.body()
                op, step = request['op'], request['step']
                attempt = store.identity(parts[1], op, step, request.get('attempt'))
                if store.fault_before(parts[1], op, step, self):
                    return
                store.fault_delay(parts[1], step)
                code, body = store.dedup(parts[1], op, step, attempt,
                                         int(request.get('permit_epoch', 1)),
                                         request.get('intent', ''), request.get('key', ''))
                if store.fault_after(parts[1], step, self):
                    return
                return self.send(code, body)
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'write':
                request = self.body()
                op, step = request['op'], request['step']
                attempt = store.identity(parts[1], op, step, request.get('attempt'))
                if store.fault_before(parts[1], op, step, self):
                    return
                store.fault_delay(parts[1], step)
                code, body = store.write(parts[1], op, step, attempt,
                                         int(request.get('permit_epoch', 1)),
                                         request.get('intent', ''),
                                         request.get('fence'),
                                         request.get('mode', 'commit'))
                if store.fault_after(parts[1], step, self):
                    return
                return self.send(code, body)
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'finalize':
                request = self.body()
                return self.send(*store.finalize(parts[1], request['op'],
                                                 request.get('fence')))
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'abort':
                request = self.body()
                return self.send(*store.abort(parts[1], request['op'],
                                              request.get('fence')))
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
            store.fault_delay(workflow, step)
            code, body = store.write(workflow, op, step, attempt,
                                     int(request.get('permit_epoch', 1)),
                                     request.get('intent', ''), None, 'commit')
            if store.fault_after(workflow, step, self):
                return
            return self.send(code, body)

    server = Server(('127.0.0.1', 0), Handler)
    server.handle_error = lambda *args: None
    save(root / 'ready.json', dict(base_url='http://127.0.0.1:' + str(server.server_port)))
    try:
        server.serve_forever(poll_interval=0.001)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
