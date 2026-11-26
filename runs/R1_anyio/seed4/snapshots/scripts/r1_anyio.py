"""R1 AnyIO capability-space source with native tasks and SQLite effects."""
import hashlib
import importlib.metadata
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import anyio
import anyio._backends._asyncio as anyio_asyncio
import anyio.to_thread

from clear_assurance import closed, digest, inspect, positive

INITIAL_TIMEOUT = float(os.environ.get('R1_INITIAL_TIMEOUT', '0.06'))
WAIT_WINDOW = float(os.environ.get('R1_WAIT_WINDOW', '0.15'))
GATE_DELAY_S = float(os.environ.get('R1_GATE_DELAY_S', '0.08'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


class Backend:
    def __init__(self, directory, route):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.route = route.copy()
        self.db_path = directory / 'effects.sqlite'
        with sqlite3.connect(self.db_path) as db:
            db.execute('create table effects(id integer primary key,operation_id text,intent text,'
                       'origin text,attempt integer,allowed integer)')
        self.lock = None
        self.entries = {}
        self.writes = []
        self.attempts = []
        self.reauth = []
        self.next_attempt = 1
        self.gate = None
        self.gate_scheduled = False
        self.task_group = None
        self.manifest = None

    def build_manifest(self, host_path):
        m = dict(adapter='anyio_task', version=importlib.metadata.version('anyio'),
                 python=sys.version.split()[0],
                 framework={'anyio._backends._asyncio': sha(Path(anyio_asyncio.__file__))},
                 worker_sha256=sha(Path(__file__)),
                 host_sha256=sha(Path(host_path)),
                 observer_sha256=sha(Path(__file__)),
                 route_sha256=digest(self.route), route=dict(self.route))
        self.manifest = m
        return m

    async def start(self):
        self.lock = anyio.Lock()
        self.gate = anyio.Event()
        self.task_group = anyio.create_task_group()
        await self.task_group.__aenter__()

    async def close(self):
        if self.task_group:
            await self.task_group.__aexit__(None, None, None)

    def append_nowait(self, operation_id, intent):
        attempt = self.next_attempt
        self.next_attempt += 1
        entry = dict(attempt=attempt, terminal=False, receipt=None, error=None,
                     done=anyio.Event(), started_ns=time.perf_counter_ns())
        self.entries[attempt] = entry
        self.attempts.append(dict(attempt=attempt, allowed=self.route.get('allowed') is True,
                                  at_ns=time.perf_counter_ns()))
        if attempt == 1 and self.route.get('delayed') and not self.gate_scheduled:
            self.gate_scheduled = True
            self.task_group.start_soon(self._open_gate_later)
        self.task_group.start_soon(self._work, attempt, operation_id, intent)
        return attempt

    async def _open_gate_later(self):
        await anyio.sleep(GATE_DELAY_S)
        self.gate.set()

    async def _work(self, attempt, operation_id, intent):
        entry = self.entries[attempt]
        try:
            if attempt == 1 and self.route.get('delayed'):
                await self.gate.wait()
            if attempt == 1 and self.route.get('outcome') == 'fail':
                entry['error'] = 'injected_failure'
                return
            async with self.lock:
                body = self._commit(attempt, operation_id, intent)
            entry['receipt'] = body
        finally:
            entry['terminal'] = True
            entry['done'].set()

    def _commit(self, attempt, operation_id, intent):
        with sqlite3.connect(self.db_path) as db:
            if self.route.get('idempotency') is True:
                row = db.execute('select id from effects where operation_id=? and intent=? '
                                 'order by id limit 1', (operation_id, intent)).fetchone()
                if row:
                    return dict(state='committed', record_id=row[0], operation_id=operation_id,
                                intent=intent, generation=1, effect_namespace='effects',
                                attempt=attempt, deduplicated=True)
            allowed = self.route.get('allowed') is True
            cur = db.execute('insert into effects(operation_id,intent,origin,attempt,allowed) '
                             'values(?,?,?,?,?)',
                             (operation_id, intent, 'original' if attempt == 1 else 'retry',
                              attempt, 1 if allowed else 0))
            self.writes.append(dict(attempt=attempt, record_id=cur.lastrowid, allowed=allowed,
                                    at_ns=time.perf_counter_ns()))
            return dict(state='committed', record_id=cur.lastrowid, operation_id=operation_id,
                        intent=intent, generation=1, effect_namespace='effects', attempt=attempt)

    async def wait_done(self, attempt, timeout):
        entry = self.entries[attempt]
        with anyio.move_on_after(timeout, shield=True) as scope:
            await entry['done'].wait()
        if scope.cancelled_caught:
            return dict(state='unknown', timeout=True, attempt=attempt)
        if entry['error']:
            return dict(state='error', error_type=entry['error'], attempt=attempt,
                        effect_namespace='effects')
        return entry['receipt']

    async def status(self, attempt):
        entry = self.entries.get(int(attempt))
        if entry is None:
            return dict(error='unknown_attempt', attempt=attempt)
        members = []
        if self.route.get('closed_registration') is True:
            members.append(dict(handle=f'root:{attempt}', parent=None,
                                terminal=entry['terminal'], error_type=entry['error'],
                                receipt=entry['receipt']))
        return dict(root=f'root:{attempt}' if members else None, members=members, attempt=attempt,
                    registration_complete=bool(self.route.get('closed_registration')),
                    effect_namespace='effects', launch_manifest=digest(self.manifest),
                    closed_registration=bool(self.route.get('closed_registration')))

    async def effects(self, operation_id, intent):
        if self.route.get('query_complete') is not True:
            return dict(state='unknown', complete=False, effect_namespace='effects',
                        operation_id=operation_id, intent=intent, generation=1)
        with sqlite3.connect(self.db_path) as db:
            rows = db.execute('select id,origin,attempt from effects where operation_id=? and '
                              'intent=? order by id', (operation_id, intent)).fetchall()
        body = dict(state='committed' if rows else 'not_committed', complete=True,
                    effect_namespace='effects', operation_id=operation_id, intent=intent,
                    generation=1, rows=[dict(record_id=r[0], origin=r[1], attempt=r[2])
                                        for r in rows])
        if rows:
            body['record_id'] = rows[0][0]
        return body

    async def describe(self):
        return dict(manifest=dict(self.manifest), route=dict(self.route),
                    capabilities=dict(executor_handle=True,
                                      closed_registration=self.route.get('closed_registration') is True),
                    tools=['append', 'effects', 'status', 'reauthorize', 'describe', 'drain'],
                    version=importlib.metadata.version('anyio'))

    async def reauthorize(self, operation_id, intent):
        self.route['allowed'] = True
        self.route['revision'] = int(self.route.get('revision', 1)) + 1
        self.manifest['route'] = dict(self.route)
        self.manifest['route_sha256'] = digest(self.route)
        self.reauth.append(dict(operation_id=operation_id, intent=intent,
                                revision=self.route['revision'], at_ns=time.perf_counter_ns()))
        return dict(state='reauthorized', allowed=True, revision=self.route['revision'],
                    operation_id=operation_id, intent=intent, generation=1,
                    effect_namespace='effects')

    async def drain(self):
        self.gate.set()
        with anyio.move_on_after(5):
            while any(not e['terminal'] for e in self.entries.values()):
                await anyio.sleep(0.005)
        with sqlite3.connect(self.db_path) as db:
            rows = db.execute('select count(*) from effects').fetchone()[0]
        return dict(drained=True, invocations=len(self.entries), effects=rows,
                    terminal=all(e['terminal'] for e in self.entries.values()))


class Host:
    def __init__(self, directory, route, patch=None):
        self.directory = directory
        self.directory.mkdir(parents=True)
        self.route = route.copy()
        self.patch = patch
        self.context = dict(operation_id=directory.name,
                            intent=hashlib.sha256(b'append r1 capability record').hexdigest(),
                            generation=1)
        self.initial_observations = []
        self.calls = []
        self.attempt = 1
        self.origin = None
        self.current_manifest = None
        self.current_route = None
        self.capabilities = None
        self.initial_qualification = None
        self.begin_ns = time.perf_counter_ns()
        self.drain_result = None
        self.close_error = None
        self.backend = None

    async def start(self):
        self.begin_ns = time.perf_counter_ns()
        self.backend = Backend(self.directory, self.route)
        await self.backend.start()
        self.backend.build_manifest(__file__)
        await self.refresh()
        self.origin = dict(context=self.context.copy(), manifest=self.current_manifest,
                           namespace='effects')
        self.initial_qualification = inspect(self.origin, self.current_manifest, self.current_route)
        attempt = self.backend.append_nowait(self.context['operation_id'],
                                             self.context['intent'])
        result = await self.backend.wait_done(attempt, INITIAL_TIMEOUT)
        if result.get('timeout'):
            outcome = 'timeout'
        elif result.get('state') == 'error':
            outcome = 'error'
        else:
            outcome = 'return_lost'
        self._count('append', outcome)
        self.initial_observations.append(dict(action='append', phase='initial', attempt=1,
                                              outcome=outcome))
        if self.patch:
            self.backend.route.update(self.patch)
            self.backend.route['revision'] = int(self.backend.route.get('revision', 1)) + 1
            self.backend.manifest['route'] = dict(self.backend.route)
            self.backend.manifest['route_sha256'] = digest(self.backend.route)

    def _count(self, tool, outcome):
        self.calls.append(dict(tool=tool, outcome=outcome, time_ns=time.perf_counter_ns()))

    async def call(self, tool, arguments):
        if tool == 'describe':
            body = await self.backend.describe()
        elif tool == 'effects':
            body = await self.backend.effects(arguments['operation_id'], arguments['intent'])
        elif tool == 'status':
            body = await self.backend.status(arguments['attempt'])
        elif tool == 'reauthorize':
            body = await self.backend.reauthorize(arguments['operation_id'], arguments['intent'])
        else:
            raise ValueError(tool)
        self._count(tool, 'return')
        return body

    async def refresh(self):
        described = await self.call('describe', {})
        self.current_manifest = described['manifest']
        self.current_route = described['route']
        self.capabilities = described['capabilities']
        return described

    async def wait(self, attempt):
        last = None
        with anyio.move_on_after(WAIT_WINDOW):
            while True:
                last = await self.call('status', {'attempt': attempt})
                if last.get('root') is None or closed(last):
                    break
                receipts = [m.get('receipt') for m in last.get('members', [])]
                if any(isinstance(r, dict) and r.get('state') == 'committed' for r in receipts):
                    break
                await anyio.sleep(0.002)
        return last

    async def retry(self):
        attempt = self.backend.append_nowait(self.context['operation_id'],
                                             self.context['intent'])
        body = await self.backend.wait_done(attempt, INITIAL_TIMEOUT)
        self.attempt = attempt
        self._count('append', 'timeout' if body.get('timeout') else
                    ('error' if body.get('state') == 'error' else 'return'))
        return body

    async def action(self, action, qualification=None):
        if action == 'wait':
            return await self.wait(self.attempt)
        if action == 'query':
            return await self.call('effects', dict(operation_id=self.context['operation_id'],
                                                   intent=self.context['intent']))
        if action == 'qualify':
            return inspect(self.origin, self.current_manifest, self.current_route)
        if action == 'retry':
            await self.refresh()
            if not qualification or not qualification.get('valid') or \
                    qualification.get('manifest') != self.current_manifest:
                return dict(state='stale_qualification', effect_namespace='effects',
                            **self.context)
            return await self.retry()
        raise ValueError(action)

    async def drain(self):
        self.drain_result = await self.backend.drain()
        self._count('drain', 'return')

    async def close(self):
        self.close_error = None
        try:
            await self.backend.close()
        except BaseException as error:
            self.close_error = dict(type=type(error).__name__, message=str(error))

    async def save(self):
        state = dict(invocations={str(k): dict(v, done=None) for k, v in self.backend.entries.items()},
                     writes=self.backend.writes, attempts=self.backend.attempts,
                     reauth=self.backend.reauth)
        save(self.directory / 'state.json', state)
        save(self.directory / 'native.json', dict(
            context=self.context, origin=self.origin, initial_route=self.route,
            initial_qualification=self.initial_qualification,
            initial_observations=self.initial_observations, attempt=self.attempt,
            calls=self.calls, capabilities=self.capabilities, drain=self.drain_result,
            close_error=self.close_error, final_manifest=dict(self.backend.manifest),
            final_route=dict(self.backend.route),
            current_qualification=inspect(self.origin, dict(self.backend.manifest),
                                          dict(self.backend.route)),
            elapsed_ns=time.perf_counter_ns() - self.begin_ns))
