"""R45: one ticket service, ten capability profiles.

Every profile runs the same five-step workload (`create`, `reserve`, `attach`,
`commit`, `notify`) and the same four fault injections.  A profile is a tuple
of six capability axes:

    closure   original call and descendants expose a terminal flag + receipt
    read      effect index: faithful / stale / unavailable
    version   writes must be bound to the current manifest version
    admission atomic "no effect + write" endpoint
    staging   fence, provisional write, finalize and abort
    dedup     atomic insert-or-return on a client-supplied key

The service knows nothing about CLEAR.  The profile is fixed for the lifetime
of the process and is reported by `/manifest`.
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
REVISED = dict(version='ticket-svc-2026.10-v2', sha='9c2d4e11')

PROFILES = {
    'C0': dict(closure=0, read='unavailable', version=0, admission=0, staging=0, dedup=0),
    'C1': dict(closure=1, read='unavailable', version=0, admission=0, staging=0, dedup=0),
    'C2': dict(closure=0, read='faithful', version=0, admission=0, staging=0, dedup=0),
    'C2s': dict(closure=0, read='stale', version=0, admission=0, staging=0, dedup=0),
    'C3': dict(closure=1, read='faithful', version=0, admission=0, staging=0, dedup=0),
    'C3s': dict(closure=1, read='stale', version=0, admission=0, staging=0, dedup=0),
    'C4': dict(closure=1, read='faithful', version=1, admission=1, staging=0, dedup=0),
    'C5': dict(closure=0, read='unavailable', version=0, admission=0, staging=1, dedup=0),
    'C6': dict(closure=1, read='faithful', version=1, admission=1, staging=1, dedup=0),
    'C7': dict(closure=0, read='unavailable', version=0, admission=0, staging=0, dedup=1),
}


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8')


class Store:
    def __init__(self, root, profile):
        self.root = Path(root)
        self.private = self.root / 'private'
        self.private.mkdir(parents=True)
        self.profile = profile
        self.axes = dict(PROFILES[profile])
        # Every write path that performs a qualification check in the same
        # transaction as the insert.  Plain writes (C0-C3) do not.
        self.atomic = bool(self.axes['admission'] or self.axes['staging']
                           or self.axes['dedup'])
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
                           'step text, attempt integer, allowed integer, manifest text, '
                           'ts integer, fence integer, key text, status text, intent text)')
                db.execute('create table if not exists fences(op text primary key, '
                           'next integer default 1, finalized integer default 0)')
                db.execute('create table if not exists rejects(id integer primary key, '
                           'op text, fence integer, reason text, ts integer)')
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

    def body(self, op, step, attempt, record_id, allowed, intent, fence, state, key=None):
        return dict(state=state, op=op, operation_id=op, step=step, record_id=record_id,
                    attempt=attempt, allowed=bool(allowed), manifest=MANIFEST['version'],
                    intent=intent, generation=1, fence=fence, key=key,
                    effect_namespace='effects')

    def reject(self, db, op, fence, reason):
        db.execute('insert into rejects(op, fence, reason, ts) values(?,?,?,?)',
                   (op, fence, reason, time.time_ns()))

    def qualified(self, workflow, permit_epoch, version):
        state = self.workflow(workflow)
        allowed = int(permit_epoch == state['epoch'] and state['allowed'])
        bound = int((not self.axes['version']) or version is None
                    or version == state['manifest']['version'])
        return allowed, bound

    def insert_effect(self, db, workflow, op, step, attempt, allowed, intent, fence,
                      status, key):
        state = self.workflow(workflow)
        cur = db.execute('insert into effects(op,step,attempt,allowed,manifest,ts,'
                         'fence,key,status,intent) values(?,?,?,?,?,?,?,?,?,?)',
                         (op, step, attempt, allowed, state['manifest']['version'],
                          time.time_ns(), fence, key, status, intent))
        body = self.body(op, step, attempt, cur.lastrowid, allowed, intent, fence,
                         status, key)
        body['manifest'] = state['manifest']['version']
        return cur.lastrowid, body

    def write(self, workflow, op, step, attempt, permit_epoch, version, intent, fence, mode):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('begin immediate')
            allowed, bound = self.qualified(workflow, permit_epoch, version)
            if self.atomic and not (allowed and bound):
                self.reject(db, op, fence, 'stale_qualification')
                db.commit()
                return 403, dict(state='stale_qualification', op=op, fence=fence,
                                 allowed=bool(allowed), bound=bool(bound))
            row = db.execute('select finalized from fences where op=?', (op,)).fetchone()
            finalized = int(row[0]) if row else 0
            if fence is not None and fence <= finalized:
                self.reject(db, op, fence, 'stale_fence')
                db.commit()
                return 409, dict(state='stale_fence', op=op, fence=fence,
                                 finalized=finalized)
            status = 'committed' if mode == 'commit' else 'provisional'
            record_id, body = self.insert_effect(db, workflow, op, step, attempt, allowed,
                                                 intent, fence, status, None)
            if status == 'committed':
                if fence is not None:
                    db.execute('insert or ignore into fences(op, next, finalized) '
                               'values(?,?,?)', (op, 1, 0))
                    db.execute('update fences set finalized=? where op=?', (fence, op))
                db.execute('update ops set terminal=1, receipt=? where op=?',
                           (json.dumps(body), op))
            db.commit()
        return 200, body

    def admit(self, workflow, op, step, attempt, permit_epoch, version, intent):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('begin immediate')
            allowed, bound = self.qualified(workflow, permit_epoch, version)
            if not (allowed and bound):
                self.reject(db, op, None, 'stale_qualification')
                db.commit()
                return 403, dict(state='stale_qualification', op=op,
                                 allowed=bool(allowed), bound=bool(bound))
            prev = db.execute('select receipt from ops where op=? and receipt is not null',
                              (op,)).fetchone()
            if prev is not None:
                body = json.loads(prev[0])
                body['deduplicated'] = True
                db.commit()
                return 200, body
            record_id, body = self.insert_effect(db, workflow, op, step, attempt, 1,
                                                 intent, None, 'committed', None)
            db.execute('update ops set terminal=1, receipt=? where op=?',
                       (json.dumps(body), op))
            db.commit()
        return 200, body

    def dedup(self, workflow, op, step, attempt, permit_epoch, version, intent, key):
        db, guard = self.guard(workflow)
        with guard:
            db.execute('begin immediate')
            allowed, bound = self.qualified(workflow, permit_epoch, version)
            if not (allowed and bound):
                self.reject(db, op, None, 'stale_qualification')
                db.commit()
                return 403, dict(state='stale_qualification', op=op,
                                 allowed=bool(allowed), bound=bool(bound))
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
            try:
                record_id, body = self.insert_effect(db, workflow, op, step, attempt, 1,
                                                     intent, None, 'committed', key)
                body['state'] = 'committed'
                db.execute('update ops set terminal=1, receipt=? where op=?',
                           (json.dumps(body), op))
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                prev = db.execute('select id, intent from effects where key=?',
                                  (key,)).fetchone()
                db.execute('insert into dedup_hits(key, op, step, ts) values(?,?,?,?)',
                           (key, op, step, time.time_ns()))
                db.commit()
                return 200, dict(state='deduplicated', duplicate=True, op=op, step=step,
                                 record_id=prev[0] if prev else None, key=key,
                                 effect_namespace='effects')
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
            body = self.body(op, step, attempt, record_id, allowed, intent, fence,
                             'committed')
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

    def close_connection(self, handler):
        handler.close_connection = True
        try:
            handler.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        handler.connection.close()
        handler.wfile = io.BytesIO()

    def fault_before(self, workflow, op, step, handler):
        """Faults that must happen before the effect is written."""
        fault = self.workflow(workflow)['faults'].get(step)
        if not fault or fault.get('fired'):
            return False
        kind = fault.get('kind')
        if kind == 'lost_before_commit':
            fault['fired'] = True
            db, guard = self.guard(workflow)
            with guard:
                db.execute('update ops set terminal=1, receipt=NULL where op=?', (op,))
                db.commit()
            self.close_connection(handler)
            return True
        if kind == 'revoke':
            fault['fired'] = True
            state = self.workflow(workflow)
            state['allowed'] = False
            state['epoch'] += 1
            state['manifest'] = dict(REVISED)
        return False

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
            self.close_connection(handler)
            return True
        return False

    def lifecycle(self, workflow, op):
        if not self.axes['closure']:
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
        if self.axes['read'] == 'unavailable':
            return 503, dict(error='unavailable', op=op)
        db, guard = self.guard(workflow)
        with guard:
            row = db.execute('select terminal, receipt from ops where op=?', (op,)).fetchone()
            rows = db.execute('select id, attempt, allowed, fence, status, intent, key '
                              'from effects where op=? order by id', (op,)).fetchall()
        if not row:
            return 404, dict(error='unknown_op', op=op)
        if self.axes['read'] == 'stale':
            return 200, dict(root=op, op=op, state='not_committed', complete=True,
                             effect_namespace='effects', rows=[])
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
            rows = db.execute("select step, count(*), "
                              "sum(case when allowed=0 then 1 else 0 end) "
                              "from effects where status='committed' group by step").fetchall()
            provisional = db.execute("select step, count(*) from effects "
                                     "where status='provisional' group by step").fetchall()
            hits = db.execute('select step, count(*) from dedup_hits group by step').fetchall()
            rejected = db.execute('select count(*) from rejects').fetchone()[0]
        held = {step: count for step, count in provisional}
        duplicated = {step: count for step, count in hits}
        return dict(steps={step: dict(rows=count, stale=stale, committed=count,
                                      provisional=held.get(step, 0),
                                      duplicates=duplicated.get(step, 0))
                           for step, count, stale in rows},
                    rejected=int(rejected))


class Server(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-root', required=True)
    parser.add_argument('--profile', required=True, choices=sorted(PROFILES))
    args = parser.parse_args()
    root = Path(args.run_root).resolve()
    store = Store(root, args.profile)

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
                return self.send(200, dict(profile=store.profile, axes=store.axes,
                                           manifest=MANIFEST))
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'manifest':
                return self.send(200, dict(profile=store.profile, axes=store.axes,
                                           manifest=store.workflow(parts[1])['manifest']))
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
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'fence':
                if not store.axes['staging']:
                    return self.send(404, dict(error='no_such_capability'))
                return self.send(200, store.allocate(parts[1], self.body()['op']))
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'admit':
                if not store.axes['admission']:
                    return self.send(404, dict(error='no_such_capability'))
                request = self.body()
                op, step = request['op'], request['step']
                attempt = store.identity(parts[1], op, step, request.get('attempt'))
                if store.fault_before(parts[1], op, step, self):
                    return
                store.fault_delay(parts[1], step)
                code, body = store.admit(parts[1], op, step, attempt,
                                         int(request.get('permit_epoch', 1)),
                                         request.get('manifest_version'),
                                         request.get('intent', ''))
                if store.fault_after(parts[1], step, self):
                    return
                return self.send(code, body)
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'dedup':
                if not store.axes['dedup']:
                    return self.send(404, dict(error='no_such_capability'))
                request = self.body()
                op, step = request['op'], request['step']
                attempt = store.identity(parts[1], op, step, request.get('attempt'))
                if store.fault_before(parts[1], op, step, self):
                    return
                store.fault_delay(parts[1], step)
                code, body = store.dedup(parts[1], op, step, attempt,
                                         int(request.get('permit_epoch', 1)),
                                         request.get('manifest_version'),
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
                                         request.get('manifest_version'),
                                         request.get('intent', ''),
                                         request.get('fence'),
                                         request.get('mode', 'commit'))
                if store.fault_after(parts[1], step, self):
                    return
                return self.send(code, body)
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'finalize':
                if not store.axes['staging']:
                    return self.send(404, dict(error='no_such_capability'))
                request = self.body()
                return self.send(*store.finalize(parts[1], request['op'],
                                                 request.get('fence')))
            if len(parts) == 3 and parts[0] == 'w' and parts[2] == 'abort':
                if not store.axes['staging']:
                    return self.send(404, dict(error='no_such_capability'))
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
                                     request.get('manifest_version'),
                                     request.get('intent', ''), None, 'commit')
            if store.fault_after(workflow, step, self):
                return
            return self.send(code, body)

    server = Server(('127.0.0.1', 0), Handler)
    server.handle_error = lambda *args: None
    save(root / 'ready.json', dict(base_url='http://127.0.0.1:' + str(server.server_port),
                                   profile=store.profile, axes=store.axes))
    try:
        server.serve_forever(poll_interval=0.001)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
