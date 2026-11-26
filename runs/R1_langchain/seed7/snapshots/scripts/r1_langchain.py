"""R1 LangChain capability-space source: action through a real StructuredTool."""
import hashlib
import importlib.metadata
import json
import sys
import time
from pathlib import Path

import anyio
from langchain_core.tools import StructuredTool

from r1_anyio import Backend, Host as AnyioHost, INITIAL_TIMEOUT
from clear_assurance import inspect


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Host(AnyioHost):
    async def start(self):
        self.begin_ns = time.perf_counter_ns()
        self.backend = Backend(self.directory, self.route)
        await self.backend.start()
        manifest = self.backend.build_manifest(__file__)
        manifest.update(adapter='langchain_structured_tool',
                        version=importlib.metadata.version('langchain-core'),
                        framework={'langchain_core.tools': sha(Path(__import__(
                            'langchain_core.tools', fromlist=['x']).__file__))})
        self.backend.manifest = manifest

        async def append(operation_id: str, intent: str) -> dict:
            attempt = self.backend.append_nowait(operation_id, intent)
            return await self.backend.wait_done(attempt, 10)

        self.tool = StructuredTool.from_function(coroutine=append, name='append',
                                                 description='Append one effect.')
        await self.refresh()
        self.origin = dict(context=self.context.copy(), manifest=self.current_manifest,
                           namespace='effects')
        self.initial_qualification = inspect(self.origin, self.current_manifest, self.current_route)
        body, outcome = await self._invoke()
        self._count('append', outcome)
        self.initial_observations.append(dict(action='append', phase='initial', attempt=1,
                                              outcome=outcome))
        if self.patch:
            self.backend.route.update(self.patch)
            self.backend.route['revision'] = int(self.backend.route.get('revision', 1)) + 1
            self.backend.manifest['route'] = dict(self.backend.route)
            self.backend.manifest['route_sha256'] = hashlib.sha256(
                json.dumps(self.backend.route, sort_keys=True,
                           separators=(',', ':')).encode()).hexdigest()

    async def _invoke(self):
        body = None
        with anyio.move_on_after(INITIAL_TIMEOUT, shield=True) as scope:
            try:
                body = await self.tool.ainvoke(dict(operation_id=self.context['operation_id'],
                                                    intent=self.context['intent']))
            except anyio.get_cancelled_exc_class():
                raise
            except BaseException as error:
                return dict(state='error', error_type=type(error).__name__), 'error'
        if scope.cancelled_caught:
            return None, 'timeout'
        if body.get('state') == 'error':
            return body, 'error'
        return body, 'return_lost'

    async def retry(self):
        body, outcome = await self._invoke()
        self._count('append', outcome)
        if outcome == 'timeout':
            return dict(state='unknown', timeout=True, effect_namespace='effects',
                        **self.context)
        return body or dict(state='error', error_type='empty_result')
