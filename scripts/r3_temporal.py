"""R3 external baseline: Temporal workflow + activity retry around one external effect."""
import asyncio
import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

TASK_QUEUE = 'r3-temporal'
MAX_ATTEMPTS = 2


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


class Store:
    def __init__(self, directory, idempotency):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db_path = self.directory / 'effects.sqlite'
        self.idempotency = bool(idempotency)
        with self._db() as db:
            db.execute('create table if not exists effects('
                       'id integer primary key,operation_id text,intent text,origin text,'
                       'attempt integer,allowed integer,at_ns integer)')
            db.execute('create table if not exists attempts('
                       'id integer primary key,attempt integer,allowed integer,at_ns integer)')
            db.execute('create table if not exists permit('
                       'id integer primary key check(id=1),allowed integer)')
            db.execute('insert or ignore into permit(id,allowed) values(1,1)')
            if self.idempotency:
                db.execute('create unique index if not exists uq_effect '
                           'on effects(operation_id,intent)')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        try:
            db.execute('pragma journal_mode=wal')
            db.execute('pragma busy_timeout=10000')
            yield db
            db.commit()
        finally:
            db.close()

    def allowed(self):
        with self._db() as db:
            row = db.execute('select allowed from permit where id=1').fetchone()
        return bool(row and row[0])

    def revoke(self):
        with self._db() as db:
            db.execute('update permit set allowed=0 where id=1')

    def record_attempt(self, attempt):
        with self._db() as db:
            allowed = db.execute('select allowed from permit where id=1').fetchone()
            db.execute('insert into attempts(attempt,allowed,at_ns) values(?,?,?)',
                       (attempt, 1 if allowed and allowed[0] else 0, time.time_ns()))

    def record(self, operation_id, intent, attempt):
        allowed = self.allowed()
        origin = 'original' if attempt == 1 else 'retry'
        values = (operation_id, intent, origin, attempt, 1 if allowed else 0, time.time_ns())
        with self._db() as db:
            if self.idempotency:
                cur = db.execute('insert or ignore into effects('
                                 'operation_id,intent,origin,attempt,allowed,at_ns) '
                                 'values(?,?,?,?,?,?)', values)
            else:
                cur = db.execute('insert into effects('
                                 'operation_id,intent,origin,attempt,allowed,at_ns) '
                                 'values(?,?,?,?,?,?)', values)
            inserted = cur.rowcount > 0
        return dict(inserted=inserted, allowed=allowed, attempt=attempt)

    def snapshot(self):
        with self._db() as db:
            rows = db.execute('select id,attempt,allowed,origin from effects order by id').fetchall()
            attempts = db.execute('select attempt,allowed from attempts order by id').fetchall()
            allowed = db.execute('select allowed from permit where id=1').fetchone()
        effects = [dict(record_id=r[0], attempt=r[1], allowed=bool(r[2]), origin=r[3]) for r in rows]
        return dict(rows=len(effects), effects=effects,
                    attempts=[dict(attempt=a[0], allowed=bool(a[1])) for a in attempts],
                    allowed=bool(allowed and allowed[0]))


@activity.defn
def commit_effect(config: dict) -> dict:
    store = Store(config['directory'], config['idempotency'])
    attempt = activity.info().attempt
    store.record_attempt(attempt)
    operation_id, intent = config['operation_id'], config['intent']
    fault, change = config['fault'], config['change']
    if attempt == 1:
        if fault == 'fail':
            try:
                raise ApplicationError('injected_failure_before_commit',
                                       type='InjectedFailure', non_retryable=False)
            finally:
                if change == 'revoke':
                    store.revoke()
        if fault == 'lost':
            store.record(operation_id, intent, attempt)
            try:
                raise ApplicationError('injected_failure_after_commit',
                                       type='InjectedFailure', non_retryable=False)
            finally:
                if change == 'revoke':
                    store.revoke()
        if fault == 'late':
            timer = None
            if change == 'revoke':
                timer = threading.Timer(config['timeout_s'], store.revoke)
                timer.daemon = True
                timer.start()
            try:
                time.sleep(config['gate_s'])
                store.record(operation_id, intent, attempt)
            finally:
                if timer:
                    timer.cancel()
            return dict(attempt=attempt, rows=store.snapshot()['rows'])
    store.record(operation_id, intent, attempt)
    return dict(attempt=attempt, rows=store.snapshot()['rows'])


@workflow.defn
class EffectWorkflow:
    @workflow.run
    async def run(self, config: dict) -> dict:
        return await workflow.execute_activity(
            commit_effect,
            config,
            start_to_close_timeout=timedelta(seconds=config['timeout_s']),
            schedule_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=MAX_ATTEMPTS,
                                     initial_interval=timedelta(milliseconds=10),
                                     backoff_coefficient=1.0),
        )


def case_id(route, change, fault):
    return f"I{int(route['idempotency'])}Q1C1G{change}F{fault}"


async def run_task(client, directory, route, change, fault, seed, gate_s, timeout_s):
    start_ns = time.perf_counter_ns()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    idem = route.get('idempotency') is True
    store = Store(directory, idem)
    operation_id = directory.name
    intent = hashlib.sha256(b'append r3 temporal record').hexdigest()
    config = dict(directory=str(directory), operation_id=operation_id, intent=intent,
                  fault=fault, change=change, idempotency=idem,
                  gate_s=gate_s, timeout_s=timeout_s)
    errors = []
    completed = False
    workflow_id = f'r3t-{case_id(route, change, fault)}-{seed}'
    try:
        await asyncio.wait_for(
            client.execute_workflow(EffectWorkflow.run, config, id=workflow_id,
                                    task_queue=TASK_QUEUE),
            timeout=20)
        completed = True
    except BaseException as error:
        errors.append(dict(type=type(error).__name__, message=str(error)))
    await asyncio.sleep(max(0.4, gate_s + 0.2))
    snapshot = store.snapshot()
    stale = [item for item in snapshot['attempts']
             if item['attempt'] > 1 and item['allowed'] is False]
    late_original = [item for item in snapshot['effects']
                     if item['attempt'] == 1 and item['allowed'] is False]
    body = dict(case=case_id(route, change, fault), seed=seed,
                terminal='complete' if completed else 'failed',
                reason='activity_retry' if completed else 'workflow_failed',
                attempts=len(snapshot['attempts']), rows=snapshot['rows'],
                effects=snapshot['effects'], duplicate=snapshot['rows'] > 1,
                stale_new=len(stale), late_original=len(late_original),
                allowed_final=snapshot['allowed'], errors=errors,
                route=route, operation_id=operation_id, intent=intent,
                workflow_id=workflow_id, gate_s=gate_s, timeout_s=timeout_s,
                elapsed_ns=time.perf_counter_ns() - start_ns)
    save(directory / 'result.json', body)
    return body
