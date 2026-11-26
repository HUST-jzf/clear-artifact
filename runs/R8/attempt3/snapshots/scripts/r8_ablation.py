"""R8 component ablation: closure, query, version binding, atomic admission."""
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

import anyio
import anyio.to_thread

INITIAL_TIMEOUT = 0.06
WAIT_WINDOW = 0.05
GATE_DELAY_S = 0.08
FLAGS = {
    'full': dict(closure=True, query=True, version=True, atomic=True),
    'no_closure': dict(closure=False, query=True, version=True, atomic=True),
    'no_query': dict(closure=True, query=False, version=True, atomic=True),
    'no_version': dict(closure=True, query=True, version=False, atomic=True),
    'no_atomic': dict(closure=True, query=True, version=True, atomic=False),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode('utf-8')).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


class Store:
    def __init__(self, directory, route):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db_path = self.directory / 'effects.sqlite'
        self.route = dict(route)
        self.lock = threading.RLock()
        self.next_attempt = 1
        self.entries = {}
        self.writes = []
        self.attempts = []
        with sqlite3.connect(self.db_path) as db:
            db.execute('create table effects(id integer primary key,operation_id text,intent text,'
                       'attempt integer,allowed integer,believed_allowed integer,'
                       'manifest_sha text,schema text,at_ns integer)')
            db.execute('create table permit(id integer primary key check(id=1),'
                       'allowed integer,revision integer)')
            db.execute('insert or replace into permit(id,allowed,revision) values(1,?,?)',
                       (1 if self.route.get('allowed') is True else 0,
                        int(self.route.get('revision', 1))))

    def set_route(self, patch):
        with self.lock:
            self.route.update(patch)
            with sqlite3.connect(self.db_path) as db:
                db.execute('update permit set allowed=?,revision=? where id=1',
                           (1 if self.route.get('allowed') is True else 0,
                            int(self.route.get('revision', 1))))

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False,
                             isolation_level=None)
        db.execute('pragma journal_mode=wal')
        db.execute('pragma busy_timeout=10000')
        return db

    def _insert(self, db, attempt, believed, manifest):
        if self.route.get('idempotency') is True:
            row = db.execute('select id from effects where operation_id=? and intent=? '
                             'order by id limit 1', (self.context['operation_id'],
                                                     self.context['intent'])).fetchone()
            if row:
                return dict(state='committed', record_id=row[0], deduplicated=True)
        allowed = 1 if self.route.get('allowed') is True else 0
        schema = self.route.get('schema')
        cur = db.execute('insert into effects(operation_id,intent,attempt,allowed,'
                         'believed_allowed,manifest_sha,schema,at_ns) values(?,?,?,?,?,?,?,?)',
                         (self.context['operation_id'], self.context['intent'], attempt,
                          allowed, 1 if believed else 0, manifest, schema,
                          time.perf_counter_ns()))
        self.writes.append(dict(attempt=attempt, record_id=cur.lastrowid,
                                allowed=bool(allowed), believed_allowed=bool(believed),
                                manifest_sha=manifest, schema=schema,
                                at_ns=time.perf_counter_ns()))
        return dict(state='committed', record_id=cur.lastrowid)

    def append(self, attempt, believed, manifest):
        with self.lock:
            self.attempts.append(dict(attempt=attempt, allowed=self.route.get('allowed') is True,
                                      at_ns=time.perf_counter_ns()))
            self.entries[attempt] = dict(terminal=False, error=None)
        if attempt == 1 and self.route.get('delayed') is True:
            time.sleep(GATE_DELAY_S)
        if attempt == 1 and self.route.get('outcome') == 'fail':
            self.entries[attempt].update(terminal=True, error='injected_failure')
            raise RuntimeError('injected_failure')
        with self.lock:
            db = self._connect()
            try:
                body = self._insert(db, attempt, believed, manifest)
            finally:
                db.close()
            self.entries[attempt].update(terminal=True)
        return body

    def retry_atomic(self, qualification, believed, manifest):
        with self.lock:
            db = self._connect()
            try:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('select allowed,revision from permit where id=1').fetchone()
                if not row[0] or row[1] != qualification['revision']:
                    db.execute('ROLLBACK')
                    return 'aborted'
                body = self._insert(db, 2, believed, manifest)
                db.execute('COMMIT')
                return body
            except BaseException:
                try:
                    db.execute('ROLLBACK')
                except BaseException:
                    pass
                raise
            finally:
                db.close()

    def effects(self):
        if self.route.get('query_complete') is not True:
            return dict(state='unknown', complete=False)
        with sqlite3.connect(self.db_path) as db:
            rows = db.execute('select id,attempt from effects where operation_id=? and intent=? '
                              'order by id', (self.context['operation_id'],
                                              self.context['intent'])).fetchall()
        return dict(state='committed' if rows else 'not_committed', complete=True,
                    rows=[dict(record_id=r[0], attempt=r[1]) for r in rows])


class Host:
    def __init__(self, directory, route, patch=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True)
        self.route = dict(route)
        self.patch = patch
        self.store = Store(self.directory, self.route)
        self.store.context = dict(operation_id=self.directory.name,
                                  intent=hashlib.sha256(b'append r8 ablation').hexdigest())
        self.attempt = 0
        self.launch = None
        self.initial_outcome = None
        self.qualified_event = threading.Event()
        self.revoked_event = threading.Event()
        if self.route.get('race_revoke') is True:
            threading.Thread(target=self._race, daemon=True).start()

    def _race(self):
        if not self.qualified_event.wait(2.0):
            return
        time.sleep(0.002)
        self.set_route(dict(allowed=False,
                            revision=int(self.route.get('revision', 1)) + 1))
        self.revoked_event.set()

    def set_route(self, patch):
        self.route.update(patch)
        self.store.set_route(patch)

    def qualify(self):
        route = dict(self.route)
        return dict(valid=route.get('allowed') is True,
                    revision=int(route.get('revision', 1)),
                    manifest=digest(route), allowed=route.get('allowed') is True)

    def status(self):
        entry = self.store.entries.get(self.attempt)
        closed = self.route.get('closed_registration') is True
        return dict(closed=closed, terminal=bool(entry and entry['terminal']),
                    error=entry['error'] if entry else None, attempt=self.attempt)

    async def wait(self, timeout):
        last = self.status()
        with anyio.move_on_after(timeout):
            while not last['closed'] or not last['terminal']:
                await anyio.sleep(0.002)
                last = self.status()
        return last

    async def start(self):
        self.launch = self.qualify()
        self.attempt = 1
        manifest = self.launch['manifest']
        outcome = 'return'
        with anyio.move_on_after(INITIAL_TIMEOUT, shield=True) as scope:
            try:
                await anyio.to_thread.run_sync(self.store.append, 1,
                                               self.launch['allowed'], manifest,
                                               abandon_on_cancel=True)
            except BaseException:
                outcome = 'error'
        if scope.cancelled_caught:
            outcome = 'timeout'
        self.initial_outcome = outcome
        if self.patch:
            self.set_route(self.patch)

    async def drain(self):
        for _ in range(300):
            if all(entry['terminal'] for entry in self.store.entries.values()):
                break
            await anyio.sleep(0.002)

    def retry_plain(self, believed):
        return self.store.append(2, believed, digest(self.route))

    def retry_atomic(self, qualification, believed):
        return self.store.retry_atomic(qualification, believed, digest(self.route))

    def effects(self):
        return self.store.effects()

    async def save(self):
        save(self.directory / 'state.json', dict(writes=self.store.writes,
                                                 attempts=self.store.attempts,
                                                 initial_outcome=self.initial_outcome))
        save(self.directory / 'native.json', dict(launch=self.launch,
                                                  final_route=dict(self.route),
                                                  initial_outcome=self.initial_outcome,
                                                  attempt=self.attempt))


def finish(terminal, reason):
    return dict(terminal=terminal, reason=reason)


async def control(host, variant):
    flags = FLAGS[variant]
    launch = host.launch
    if flags['version'] and not launch['valid']:
        return finish('pause', 'stale_qualification')
    if host.route.get('race_revoke') is True:
        host.qualified_event.set()
        host.revoked_event.wait(2.0)
    state = host.status() if (not flags['query'] or not flags['closure']) else \
        await host.wait(WAIT_WINDOW)
    if not flags['query']:
        if state['closed'] and state['terminal'] and not state['error']:
            return finish('complete', 'status_success')
        return await do_retry(host, launch, flags,
                              recheck=host.route.get('race_revoke') is not True,
                              reason='no_query')
    effect = host.effects()
    if effect['state'] == 'committed':
        return finish('complete', 'query_committed')
    if effect['state'] == 'unknown':
        if not flags['closure']:
            return await do_retry(host, launch, flags,
                                  recheck=host.route.get('race_revoke') is not True,
                                  reason='query_unknown')
        return finish('pause', 'query_unknown')
    if state['closed'] and state['error']:
        return await do_retry(host, launch, flags,
                              recheck=host.route.get('race_revoke') is not True,
                              reason='closed_error')
    if not state['closed']:
        if not flags['closure']:
            return await do_retry(host, launch, flags,
                                  recheck=host.route.get('race_revoke') is not True,
                                  reason='closure_missing')
        for _ in range(10):
            await anyio.sleep(0.02)
            effect = host.effects()
            if effect['state'] == 'committed':
                return finish('complete', 'late_commit')
            if effect['state'] == 'unknown':
                return finish('pause', 'query_unknown')
        return finish('pause', 'no_effect')
    return finish('pause', 'unexpected')


async def do_retry(host, launch, flags, recheck, reason):
    if recheck and flags['version']:
        current = host.qualify()
        if not current['valid'] or current['manifest'] != launch['manifest'] or \
                current['revision'] != launch['revision']:
            return finish('pause', 'stale_qualification')
    if flags['atomic']:
        body = host.retry_atomic(launch, True)
        if body == 'aborted':
            return finish('pause', 'atomic_abort')
    else:
        body = host.retry_plain(True)
    return finish('complete' if body.get('state') == 'committed' else 'pause', reason)
