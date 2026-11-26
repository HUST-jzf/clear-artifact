"""R1 host: MCP stdio session with bounded observations for capability-space cells."""
import hashlib
import json
import os
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from clear_assurance import closed, digest, inspect, positive

INITIAL_TIMEOUT = float(os.environ.get('R1_INITIAL_TIMEOUT', '0.06'))
WAIT_WINDOW = float(os.environ.get('R1_WAIT_WINDOW', '0.15'))
ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def payload(result):
    if result.structuredContent:
        return result.structuredContent
    for item in result.content:
        text = getattr(item, 'text', None)
        if text is not None:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return dict(state='error', raw=text)
    return dict(state='error', raw='empty_result')


class Host:
    def __init__(self, directory, route, patch=None):
        directory.mkdir(parents=True)
        self.directory = directory
        self.route_path = directory / 'route.json'
        self.route_path.write_text(json.dumps(route), encoding='utf-8')
        self.initial_route = route.copy()
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
        self.stack = AsyncExitStack()
        self.session = None
        self.errlog = None
        self.begin_ns = None
        self.drain_result = None
        self.close_error = None

    async def start(self):
        self.begin_ns = time.perf_counter_ns()
        self.errlog = (self.directory / 'server.stderr').open('w', encoding='utf-8')
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / 'scripts/r1_server.py'), '--state', str(self.directory),
                  '--host', str(Path(__file__).resolve())],
            env=dict(os.environ))
        read, write = await self.stack.enter_async_context(stdio_client(params, errlog=self.errlog))
        self.session = await self.stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        await self.refresh()
        self.origin = dict(context=self.context.copy(), manifest=self.current_manifest,
                           namespace='effects')
        self.initial_qualification = inspect(self.origin, self.current_manifest, self.current_route)
        with anyio.move_on_after(INITIAL_TIMEOUT, shield=True) as scope:
            result = await self.session.call_tool('append', self.context)
        if scope.cancelled_caught:
            self._count('append', 'timeout')
            self.initial_observations.append(dict(action='append', phase='initial', attempt=1,
                                                  outcome='timeout', timeout=INITIAL_TIMEOUT))
        else:
            self._count('append', 'error' if result.isError else 'return')
            self.initial_observations.append(dict(action='append', phase='initial', attempt=1,
                                                  outcome='error' if result.isError else 'return_lost'))
        await anyio.sleep(0.002)
        if self.patch:
            current = json.loads(self.route_path.read_text(encoding='utf-8'))
            current.update(self.patch)
            self.route_path.write_text(json.dumps(current), encoding='utf-8')

    def _count(self, tool, outcome):
        self.calls.append(dict(tool=tool, outcome=outcome, time_ns=time.perf_counter_ns()))

    async def call(self, tool, arguments):
        result = await self.session.call_tool(tool, arguments)
        self._count(tool, 'error' if result.isError else 'return')
        if result.isError:
            return dict(state='error', error_type='tool_error', text=''.join(
                getattr(c, 'text', '') for c in result.content))
        return payload(result)

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
                if last.get('root') is None:
                    break
                if closed(last):
                    break
                receipts = [m.get('receipt') for m in last.get('members', [])]
                if any(isinstance(r, dict) and r.get('state') == 'committed' for r in receipts):
                    break
                await anyio.sleep(0.002)
        return last

    async def retry(self):
        with anyio.move_on_after(INITIAL_TIMEOUT, shield=True) as scope:
            result = await self.session.call_tool('append', self.context)
        if scope.cancelled_caught:
            self._count('append', 'timeout')
            self.attempt += 1
            return dict(state='unknown', timeout=True, effect_namespace='effects',
                        **self.context)
        self._count('append', 'error' if result.isError else 'return')
        body = payload(result)
        if result.isError:
            body = dict(body, state='error', error_type='tool_error')
        self.attempt += 1
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
                return dict(state='stale_qualification', effect_namespace='effects', **self.context)
            return await self.retry()
        raise ValueError(action)

    async def drain(self):
        try:
            result = await self.session.call_tool('drain', {})
            self._count('drain', 'error' if result.isError else 'return')
            self.drain_result = payload(result)
        except BaseException as error:
            self.drain_result = dict(drained=False, error=type(error).__name__)

    async def close(self):
        self.close_error = None
        try:
            await self.stack.aclose()
        except BaseException as error:
            self.close_error = dict(type=type(error).__name__, message=str(error))
        if self.errlog:
            self.errlog.close()

    async def save(self):
        final_route = json.loads(self.route_path.read_text(encoding='utf-8'))
        save(self.directory / 'native.json', dict(
            context=self.context, origin=self.origin, initial_route=self.initial_route,
            initial_qualification=self.initial_qualification,
            initial_observations=self.initial_observations, attempt=self.attempt,
            calls=self.calls, capabilities=self.capabilities, drain=self.drain_result,
            close_error=self.close_error, final_manifest=self.current_manifest,
            final_route=final_route,
            current_qualification=inspect(self.origin, self.current_manifest, final_route),
            elapsed_ns=time.perf_counter_ns() - self.begin_ns))
