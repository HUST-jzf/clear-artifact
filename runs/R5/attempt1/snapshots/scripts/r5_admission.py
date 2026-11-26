"""R5 concurrency/revocation race: two controllers and one environment over SQLite."""
import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


class Store:
    def __init__(self, path, idempotency):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.idempotency = bool(idempotency)
        with self._db() as db:
            db.execute('create table if not exists effects('
                       'id integer primary key,operation_id text,intent text,'
                       'controller text,allowed integer,revision integer,at_ns integer)')
            db.execute('create table if not exists permit('
                       'id integer primary key check(id=1),allowed integer,revision integer)')
            db.execute('create table if not exists controllers('
                       'id integer primary key,controller text,outcome text,at_ns integer)')
            db.execute('insert or ignore into permit(id,allowed,revision) values(1,1,1)')
            if self.idempotency:
                db.execute('create unique index if not exists uq_effect '
                           'on effects(operation_id,intent)')

    def _connect(self, isolation=None):
        db = sqlite3.connect(self.path, timeout=10.0, check_same_thread=False,
                             isolation_level=isolation)
        db.execute('pragma journal_mode=wal')
        db.execute('pragma busy_timeout=10000')
        return db

    @contextmanager
    def _db(self):
        db = self._connect()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def read_permit(self):
        with self._db() as db:
            row = db.execute('select allowed,revision from permit where id=1').fetchone()
        return dict(allowed=bool(row[0]), revision=row[1])

    def query_effect(self, operation_id, intent):
        with self._db() as db:
            return db.execute('select id from effects where operation_id=? and intent=?',
                              (operation_id, intent)).fetchone() is not None

    def insert(self, operation_id, intent, controller):
        permit = self.read_permit()
        with self._db() as db:
            if self.idempotency:
                cur = db.execute('insert or ignore into effects('
                                 'operation_id,intent,controller,allowed,revision,at_ns) '
                                 'values(?,?,?,?,?,?)',
                                 (operation_id, intent, controller,
                                  1 if permit['allowed'] else 0, permit['revision'],
                                  time.time_ns()))
            else:
                cur = db.execute('insert into effects('
                                 'operation_id,intent,controller,allowed,revision,at_ns) '
                                 'values(?,?,?,?,?,?)',
                                 (operation_id, intent, controller,
                                  1 if permit['allowed'] else 0, permit['revision'],
                                  time.time_ns()))
            inserted = cur.rowcount > 0
        return dict(outcome='inserted' if inserted else 'existing', allowed=permit['allowed'])

    def clear_admit(self, operation_id, intent, controller, qualified_revision):
        db = self._connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('select allowed,revision from permit where id=1').fetchone()
            if not row[0] or row[1] != qualified_revision:
                db.execute('ROLLBACK')
                return dict(outcome='aborted', allowed=False, revision=row[1])
            exists = db.execute('select id from effects where operation_id=? and intent=?',
                                (operation_id, intent)).fetchone()
            if exists:
                db.execute('COMMIT')
                return dict(outcome='existing', allowed=True, revision=row[1])
            db.execute('insert into effects(operation_id,intent,controller,allowed,revision,at_ns) '
                       'values(?,?,?,?,?,?)',
                       (operation_id, intent, controller, 1, row[1], time.time_ns()))
            db.execute('COMMIT')
            return dict(outcome='inserted', allowed=True, revision=row[1])
        except BaseException:
            try:
                db.execute('ROLLBACK')
            except BaseException:
                pass
            raise
        finally:
            db.close()

    def reauthorize(self):
        with self._db() as db:
            db.execute('update permit set allowed=1,revision=revision+1 where id=1')

    def revoke(self):
        with self._db() as db:
            db.execute('update permit set allowed=0,revision=revision+1 where id=1')

    def record_controller(self, controller, outcome):
        with self._db() as db:
            db.execute('insert into controllers(controller,outcome,at_ns) values(?,?,?)',
                       (controller, outcome, time.time_ns()))

    def snapshot(self):
        with self._db() as db:
            rows = db.execute('select id,controller,allowed,revision from effects '
                              'order by id').fetchall()
            controllers = db.execute('select controller,outcome from controllers '
                                     'order by id').fetchall()
            permit = db.execute('select allowed,revision from permit where id=1').fetchone()
        effects = [dict(record_id=r[0], controller=r[1], allowed=bool(r[2]),
                        revision=r[3]) for r in rows]
        return dict(rows=len(effects), effects=effects,
                    controllers=[dict(controller=c[0], outcome=c[1]) for c in controllers],
                    permit=dict(allowed=bool(permit[0]), revision=permit[1]))


def controller(policy, db_path, idempotency, operation_id, intent, name,
               qualification_barrier, write_barrier, stagger):
    store = Store(db_path, idempotency)
    outcome = None
    try:
        qualified = store.read_permit() if policy == 'clear' else None
        seen = store.query_effect(operation_id, intent) if policy == 'query_retry' else None
        qualification_barrier.wait()
        write_barrier.wait()
        time.sleep(stagger)
        if policy == 'pause':
            outcome = 'paused'
        elif policy == 'clear':
            body = store.clear_admit(operation_id, intent, name, qualified['revision'])
            outcome = body['outcome']
        elif policy == 'idem_retry':
            outcome = store.insert(operation_id, intent, name)['outcome']
        elif policy == 'query_retry':
            if seen:
                outcome = 'existing'
            else:
                outcome = store.insert(operation_id, intent, name)['outcome']
        elif policy == 'reauth_retry':
            if not store.read_permit()['allowed']:
                store.reauthorize()
            outcome = store.insert(operation_id, intent, name)['outcome']
        else:
            raise ValueError(policy)
    finally:
        store.record_controller(name, outcome or 'error')


def run(directory, change, idempotency, policy, seed):
    start_ns = time.perf_counter_ns()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    db_path = directory / 'effects.sqlite'
    store = Store(db_path, idempotency)
    operation_id = directory.name
    intent = hashlib.sha256(b'append r5 race record').hexdigest()
    qualification_barrier = threading.Barrier(3, timeout=10)
    write_barrier = threading.Barrier(3, timeout=10)
    errors = []
    threads = []
    for index, name in enumerate(['c1', 'c2']):
        stagger = 0.001 * ((seed + index) % 3)
        thread = threading.Thread(target=controller,
                                  args=(policy, db_path, idempotency, operation_id, intent,
                                        name, qualification_barrier, write_barrier, stagger))
        thread.start()
        threads.append(thread)
    try:
        qualification_barrier.wait()
        if change == 'revoke':
            store.revoke()
        write_barrier.wait()
        for thread in threads:
            thread.join(timeout=15)
    except BaseException as error:
        errors.append(dict(type=type(error).__name__, message=str(error)))
    for thread in threads:
        if thread.is_alive():
            errors.append(dict(type='TimeoutError', message='controller did not finish'))
    snapshot = store.snapshot()
    stale = [item for item in snapshot['effects'] if item['allowed'] is False]
    body = dict(case=f'G{change}I{int(idempotency)}', policy=policy, seed=seed,
                terminal='complete' if snapshot['rows'] == 1 else 'not_complete',
                rows=snapshot['rows'], effects=snapshot['effects'],
                controllers=snapshot['controllers'], permit=snapshot['permit'],
                duplicate=snapshot['rows'] > 1, stale_new=len(stale),
                aborted=sum(1 for c in snapshot['controllers'] if c['outcome'] == 'aborted'),
                errors=errors, operation_id=operation_id, intent=intent,
                elapsed_ns=time.perf_counter_ns() - start_ns)
    save(directory / 'result.json', body)
    return body
