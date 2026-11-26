"""R27: CLEAR packaged as a decorator around one framework tool call."""
import functools
import time

import anyio
from clear_assurance import decide, digest, inspect
from r4_holdout import Host


class GuardHost(Host):
    """R4 host with the initial call moved inside the decorated tool."""

    async def prepare(self):
        await anyio.to_thread.run_sync(lambda: None)
        self.begin_ns = time.perf_counter_ns()
        self.current_manifest = self.manifest()
        self.current_route = dict(self.store.route)
        self.capabilities = dict(
            executor_handle=True,
            closed_registration=self.store.route.get('closed_registration') is True)
        self.origin = dict(context=self.context.copy(), manifest=self.current_manifest,
                           namespace='effects')
        self.initial_qualification = inspect(self.origin, self.current_manifest,
                                             self.current_route)

    def apply_patch(self):
        if self.patch:
            self.change_route(self.patch)

    async def first_attempt(self):
        body = await self.invoke()
        self._count('append', self.last_outcome)
        self.initial_observations.append(dict(action='append', phase='initial', attempt=1,
                                              outcome=self.last_outcome))
        return body


def guarded(host, budget=4, after_initial=None):
    """Wrap an async tool call: invoke once, then follow decide() to a terminal."""

    def decorate(invoke):
        @functools.wraps(invoke)
        async def wrapper(*args, **kwargs):
            qualification = host.initial_qualification
            events = []
            body = await invoke(*args, **kwargs)
            if after_initial is not None:
                after_initial()
            while True:
                await host.refresh()
                decision = decide(host.origin, host.current_manifest, host.capabilities,
                                  qualification, events, budget)
                action = decision['action']
                if action in ('pause', 'complete'):
                    return dict(terminal=action, reason=decision['reason'], body=body,
                                events=events, steps=[])
                body = await host.action(action, qualification=qualification)
                events.append(dict(seq=len(events), context=host.context.copy(),
                                   manifest=digest(host.current_manifest), action=action,
                                   body=body))
                if action == 'qualify':
                    qualification = body

        return wrapper

    return decorate
