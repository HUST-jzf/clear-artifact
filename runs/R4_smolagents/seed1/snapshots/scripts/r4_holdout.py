"""R4 holdout adapters: one tool call through a single framework tool."""
import hashlib
import importlib
import importlib.metadata
import json
import sqlite3
import threading
import time
from pathlib import Path

import anyio
import anyio.to_thread

from clear_assurance import closed, digest, inspect, positive

INITIAL_TIMEOUT = 0.06
WAIT_WINDOW = 0.15
GATE_DELAY_S = 0.08
FRAMEWORKS = {'smolagents': ('smolagents', 'smolagents'),
              'pydantic_ai': ('pydantic_ai', 'pydantic-ai-slim'),
              'llamaindex': ('llama_index.core', 'llama-index-core'),
              'autogen': ('autogen_core', 'autogen-core')}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
                       'origin text,attempt integer,allowed integer)')

    def append(self, operation_id, intent):
        with self.lock:
            attempt = self.next_attempt
            self.next_attempt += 1
            self.entries[attempt] = dict(attempt=attempt, terminal=False, receipt=None, error=None)
            self.attempts.append(dict(attempt=attempt, allowed=self.route.get('allowed') is True,
                                      at_ns=time.perf_counter_ns()))
        route = dict(self.route)
        if attempt == 1 and route.get('delayed'):
            time.sleep(GATE_DELAY_S)
        if attempt == 1 and route.get('outcome') == 'fail':
            self.entries[attempt].update(error='injected_failure', terminal=True)
            raise RuntimeError('injected_failure')
        with self.lock, sqlite3.connect(self.db_path) as db:
            if route.get('idempotency') is True:
                row = db.execute('select id from effects where operation_id=? and intent=? '
                                 'order by id limit 1', (operation_id, intent)).fetchone()
                if row:
                    body = dict(state='committed', record_id=row[0], operation_id=operation_id,
                                intent=intent, generation=1, effect_namespace='effects',
                                attempt=attempt, deduplicated=True)
                    self.entries[attempt].update(receipt=body, terminal=True)
                    return body
            allowed = route.get('allowed') is True
            cur = db.execute('insert into effects(operation_id,intent,origin,attempt,allowed) '
                             'values(?,?,?,?,?)',
                             (operation_id, intent, 'original' if attempt == 1 else 'retry',
                              attempt, 1 if allowed else 0))
            self.writes.append(dict(attempt=attempt, record_id=cur.lastrowid, allowed=allowed,
                                    at_ns=time.perf_counter_ns()))
            body = dict(state='committed', record_id=cur.lastrowid, operation_id=operation_id,
                        intent=intent, generation=1, effect_namespace='effects', attempt=attempt)
        self.entries[attempt].update(receipt=body, terminal=True)
        return body

    def effects(self, operation_id, intent):
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

    def reauthorize(self, operation_id, intent):
        self.route['allowed'] = True
        self.route['revision'] = int(self.route.get('revision', 1)) + 1
        return dict(state='reauthorized', allowed=True, revision=self.route['revision'],
                    operation_id=operation_id, intent=intent, generation=1,
                    effect_namespace='effects')


class SmolagentsAdapter:
    framework = 'smolagents'

    def __init__(self, store):
        from smolagents import Tool

        class AppendTool(Tool):
            name = 'append'
            description = 'Append one effect to the store.'
            inputs = {'operation_id': {'type': 'string', 'description': 'operation id'},
                      'intent': {'type': 'string', 'description': 'intent digest'}}
            output_type = 'object'

            def forward(self, operation_id, intent):
                return store.append(operation_id, intent)

        self.tool = AppendTool()

    async def call(self, operation_id, intent):
        return await anyio.to_thread.run_sync(
            lambda: self.tool(operation_id=operation_id, intent=intent),
            abandon_on_cancel=True)


class PydanticAIAdapter:
    framework = 'pydantic_ai'

    def __init__(self, store):
        from pydantic_ai import Tool

        async def append(operation_id: str, intent: str) -> dict:
            return await anyio.to_thread.run_sync(store.append, operation_id, intent,
                                                  abandon_on_cancel=True)

        self.tool = Tool(append, name='append',
                         description='Append one effect to the store.')

    async def call(self, operation_id, intent):
        return await self.tool.function_schema.call(
            {'operation_id': operation_id, 'intent': intent}, None)


class LlamaIndexAdapter:
    framework = 'llamaindex'

    def __init__(self, store):
        from llama_index.core.tools import FunctionTool

        async def append(operation_id: str, intent: str) -> dict:
            return await anyio.to_thread.run_sync(store.append, operation_id, intent,
                                                  abandon_on_cancel=True)

        self.tool = FunctionTool.from_defaults(async_fn=append, name='append',
                                               description='Append one effect to the store.')

    async def call(self, operation_id, intent):
        output = await self.tool.acall(operation_id=operation_id, intent=intent)
        return output.raw_output


class AutoGenAdapter:
    framework = 'autogen'

    def __init__(self, store):
        from autogen_core.tools import FunctionTool

        async def append(operation_id: str, intent: str) -> dict:
            return await anyio.to_thread.run_sync(store.append, operation_id, intent,
                                                  abandon_on_cancel=True)

        self.tool = FunctionTool(append, description='Append one effect to the store.',
                                 name='append')

    async def call(self, operation_id, intent):
        from autogen_core import CancellationToken

        return await self.tool.run_json({'operation_id': operation_id, 'intent': intent},
                                        CancellationToken())


class Host:
    def __init__(self, directory, route, adapter, patch=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True)
        self.patch = patch
        self.initial_route = dict(route)
        self.route_path = self.directory / 'route.json'
        self.route_path.write_text(json.dumps(route), encoding='utf-8')
        self.context = dict(operation_id=self.directory.name,
                            intent=hashlib.sha256(b'append r4 holdout record').hexdigest(),
                            generation=1)
        self.store = Store(self.directory, route)
        self.adapter = adapter(self.store)
        self.initial_observations = []
        self.calls = []
        self.attempt = 0
        self.origin = None
        self.current_manifest = None
        self.current_route = None
        self.capabilities = None
        self.initial_qualification = None
        self.begin_ns = time.perf_counter_ns()
        self.last_outcome = None
        self.drain_result = None

    def manifest(self):
        module = importlib.import_module(FRAMEWORKS[self.adapter.framework][0])
        distribution = FRAMEWORKS[self.adapter.framework][1]
        return dict(adapter=self.adapter.framework + '_tool',
                    version=importlib.metadata.version(distribution),
                    python='3.13.2',
                    framework={module.__name__: sha(module.__file__)},
                    worker_sha256=sha(Path(__file__)),
                    host_sha256=sha(Path(__file__)),
                    observer_sha256=sha(Path(__file__)),
                    route_sha256=digest(self.store.route), route=dict(self.store.route))

    def _count(self, tool, outcome):
        self.calls.append(dict(tool=tool, outcome=outcome, time_ns=time.perf_counter_ns()))

    async def invoke(self):
        self.attempt += 1
        result = None
        error = None
        with anyio.move_on_after(INITIAL_TIMEOUT, shield=True) as scope:
            try:
                result = await self.adapter.call(self.context['operation_id'],
                                                 self.context['intent'])
            except Exception as caught:
                error = caught
        if scope.cancelled_caught:
            self.last_outcome = 'timeout'
            return dict(state='unknown', timeout=True, effect_namespace='effects',
                        **self.context)
        if error is not None:
            self.last_outcome = 'error'
            return dict(state='error', error_type=type(error).__name__,
                        effect_namespace='effects', **self.context)
        self.last_outcome = 'return'
        return result

    async def start(self):
        # Pay thread-pool creation before the timed call, so a 50-90 ms timeout is not
        # consumed by starting the first worker thread.
        await anyio.to_thread.run_sync(lambda: None)
        self.begin_ns = time.perf_counter_ns()
        self.current_manifest = self.manifest()
        self.current_route = dict(self.store.route)
        self.capabilities = dict(executor_handle=True,
                                 closed_registration=self.store.route.get('closed_registration') is True)
        self.origin = dict(context=self.context.copy(), manifest=self.current_manifest,
                           namespace='effects')
        self.initial_qualification = inspect(self.origin, self.current_manifest, self.current_route)
        body = await self.invoke()
        self._count('append', self.last_outcome)
        self.initial_observations.append(dict(action='append', phase='initial', attempt=1,
                                              outcome=self.last_outcome))
        if self.patch:
            self.change_route(self.patch)
        return body

    def change_route(self, patch):
        self.store.route.update(patch)
        self.store.route['revision'] = int(self.store.route.get('revision', 1)) + 1
        self.route_path.write_text(json.dumps(self.store.route), encoding='utf-8')
        self.current_manifest = self.manifest()
        self.current_route = dict(self.store.route)
        self.capabilities = dict(executor_handle=True,
                                 closed_registration=self.store.route.get('closed_registration') is True)

    async def call(self, tool, arguments):
        if tool == 'describe':
            body = dict(manifest=dict(self.current_manifest), route=dict(self.current_route),
                        capabilities=dict(self.capabilities),
                        tools=['append', 'effects', 'status', 'reauthorize', 'describe', 'drain'],
                        version=self.current_manifest['version'])
        elif tool == 'effects':
            body = self.store.effects(arguments['operation_id'], arguments['intent'])
        elif tool == 'status':
            body = self.status(arguments['attempt'])
        elif tool == 'reauthorize':
            body = self.store.reauthorize(arguments['operation_id'], arguments['intent'])
            self.current_manifest = self.manifest()
            self.current_route = dict(self.store.route)
        else:
            raise ValueError(tool)
        self._count(tool, 'return')
        return body

    def status(self, attempt):
        entry = self.store.entries.get(int(attempt))
        members = []
        if self.store.route.get('closed_registration') is True and entry:
            members.append(dict(handle='root', parent=None, terminal=entry['terminal'],
                                error_type=entry['error'], receipt=entry['receipt']))
        return dict(root='root' if members else None, members=members, attempt=attempt,
                    registration_complete=bool(self.store.route.get('closed_registration')),
                    effect_namespace='effects', launch_manifest=digest(self.current_manifest),
                    closed_registration=bool(self.store.route.get('closed_registration')))

    async def wait(self):
        last = None
        with anyio.move_on_after(WAIT_WINDOW):
            while True:
                last = await self.call('status', {'attempt': self.attempt})
                if last.get('root') is None or closed(last):
                    break
                receipts = [m.get('receipt') for m in last.get('members', [])]
                if any(isinstance(r, dict) and r.get('state') == 'committed' for r in receipts):
                    break
                await anyio.sleep(0.002)
        return last

    async def retry(self):
        return await self.invoke()

    async def action(self, action, qualification=None):
        if action == 'wait':
            return await self.wait()
        if action == 'query':
            return await self.call('effects', dict(operation_id=self.context['operation_id'],
                                                   intent=self.context['intent']))
        if action == 'qualify':
            return inspect(self.origin, self.current_manifest, self.current_route)
        if action == 'retry':
            self.current_manifest = self.manifest()
            self.current_route = dict(self.store.route)
            if not qualification or not qualification.get('valid') or \
                    qualification.get('manifest') != self.current_manifest:
                return dict(state='stale_qualification', effect_namespace='effects',
                            **self.context)
            return await self.retry()
        raise ValueError(action)

    async def refresh(self):
        return await self.call('describe', {})

    async def drain(self):
        for _ in range(10000):
            if all(entry['terminal'] for entry in self.store.entries.values()):
                break
            await anyio.sleep(0.001)
        with sqlite3.connect(self.store.db_path) as db:
            rows = db.execute('select count(*) from effects').fetchone()[0]
        self.drain_result = dict(drained=True, invocations=len(self.store.entries), effects=rows,
                                 terminal=all(entry['terminal']
                                              for entry in self.store.entries.values()))
        self._count('drain', 'return')

    async def save(self):
        save(self.directory / 'native.json', dict(
            context=self.context, origin=self.origin, initial_route=self.initial_route,
            initial_qualification=self.initial_qualification,
            initial_observations=self.initial_observations, attempt=self.attempt,
            calls=self.calls, capabilities=self.capabilities, drain=self.drain_result,
            final_manifest=self.current_manifest,
            final_route=json.loads(self.route_path.read_text(encoding='utf-8')),
            current_qualification=inspect(self.origin, self.current_manifest,
                                          json.loads(self.route_path.read_text(encoding='utf-8'))),
            elapsed_ns=time.perf_counter_ns() - self.begin_ns))
        save(self.directory / 'state.json', dict(writes=self.store.writes,
                                                 attempts=self.store.attempts,
                                                 entries={str(k): dict(v) for k, v in
                                                          self.store.entries.items()}))
