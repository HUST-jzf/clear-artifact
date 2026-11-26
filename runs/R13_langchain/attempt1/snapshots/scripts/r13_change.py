"""R13 change-after-evidence campaign.

Faults mutate the destination (image manifest or permit) while the controller is
recovering, so the original evidence no longer describes the deployment that would
accept a retry. Sources are the in-process AnyIO and LangChain hosts used by R2.
"""
import hashlib
import json
import os
import random
import time
from pathlib import Path

from clear_assurance import digest
from r1_anyio import Host as _AnyIOHost

try:
    from r1_langchain import Host as _LangChainHost
except ImportError:
    _LangChainHost = None

MODES = ['manifest_change', 'revoke_before_recovery', 'revoke_after_query',
         'revoke_during_requalification']
SOURCES = {'anyio': _AnyIOHost, 'langchain': _LangChainHost}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def parameters(mode, seed):
    rng = random.Random((seed + 1) * 1000033 + MODES.index(mode) * 7919)
    return dict(initial_timeout=rng.uniform(0.05, 0.09), gate=0.0, wait_window=0.15)


def route_for(mode):
    return dict(revision=1, mode='inline', outcome='fail', delayed=False,
                abandon_on_cancel=False, delegated=False, closed_registration=True,
                allowed=True, store='effects', idempotency=False, query_complete=True,
                change=mode)


def configure(source, timeout, wait, gate):
    os.environ['R1_INITIAL_TIMEOUT'] = repr(timeout)
    os.environ['R1_WAIT_WINDOW'] = repr(wait)
    os.environ['R1_GATE_DELAY_S'] = repr(gate)
    import r1_anyio
    r1_anyio.INITIAL_TIMEOUT = timeout
    r1_anyio.WAIT_WINDOW = wait
    r1_anyio.GATE_DELAY_S = gate
    if source == 'langchain':
        import r1_langchain
        r1_langchain.INITIAL_TIMEOUT = timeout


class Mutation:
    """Shared helpers for hosts that change the destination once."""

    def mutate(self, changes):
        self.backend.route.update(changes)
        self.backend.route['revision'] = int(self.backend.route.get('revision', 1)) + 1
        self.backend.manifest['route'] = dict(self.backend.route)
        self.backend.manifest['route_sha256'] = digest(self.backend.route)
        self.mutations.append(dict(changes=dict(changes),
                                   revision=self.backend.route['revision'],
                                   at_ns=time.perf_counter_ns()))
        return self.backend.route['revision']


class ManifestChange(Mutation):
    """The executor image is replaced right after the original attempt."""

    async def start(self):
        await super().start()
        self.backend.manifest['worker_sha256'] = 'redeploy-' + digest(self.backend.manifest)[:16]
        self.mutations.append(dict(changes={'worker_sha256': 'redeploy'},
                                   revision=self.backend.route.get('revision', 1),
                                   at_ns=time.perf_counter_ns()))


class RevokeBeforeRecovery(Mutation):
    """The permit is revoked as soon as the original attempt returns."""

    async def start(self):
        await super().start()
        self.mutate({'allowed': False})


class RevokeAfterQuery(Mutation):
    """The permit is revoked immediately after the controller's first effect query."""

    async def call(self, tool, arguments):
        body = await super().call(tool, arguments)
        if tool == 'effects' and not self.revoked:
            self.revoked = True
            self.mutate({'allowed': False})
        return body


class RevokeDuringRequalification(Mutation):
    """Version bumps after the original attempt; the permit is revoked at the retry.

    A benign revision bump forces the controller to rebuild qualification; revoking the
    permit only when the controller actually attempts the retry opens a TOCTOU window
    between the recorded qualification and the write.
    """

    async def call(self, tool, arguments):
        body = await super().call(tool, arguments)
        if tool == 'status' and not self.bumped and body.get('root'):
            self.bumped = True
            self.mutate({})
        return body

    async def action(self, action, qualification=None):
        if action == 'retry' and self.armed and not self.revoked:
            self.revoked = True
            self.mutate({'allowed': False})
        body = await super().action(action, qualification)
        if action == 'qualify':
            self.armed = True
        return body


HOOKS = {
    'manifest_change': ManifestChange,
    'revoke_before_recovery': RevokeBeforeRecovery,
    'revoke_after_query': RevokeAfterQuery,
    'revoke_during_requalification': RevokeDuringRequalification,
}


def make_host(source, directory, mode):
    base = SOURCES[source]
    if base is None:
        raise RuntimeError(f'source {source} unavailable in this environment')
    hook = HOOKS[mode]
    cls = type('R13Host', (hook, base), {})
    host = cls(directory, route_for(mode), None)
    host.mutations = []
    host.revoked = False
    host.armed = False
    host.bumped = False
    return host


async def task(run, source, case, policy):
    from r1_policies import run as control
    directory = run / f"S{case['seed']}_{case['mode']}_{policy}"
    params = parameters(case['mode'], case['seed'])
    configure(source, params['initial_timeout'], params['wait_window'], params['gate'])
    host = make_host(source, directory, case['mode'])
    result = None
    try:
        await host.start()
        result = await control(host, policy)
        result.update(case=case['id'], mode=case['mode'], seed=case['seed'],
                      policy=policy, params=params,
                      mutations=host.mutations,
                      elapsed_ns=time.perf_counter_ns() - host.begin_ns)
        save(directory / 'result.json', result)
    except BaseException as error:
        save(directory / 'failure.json', dict(type=type(error).__name__, message=str(error)))
        raise
    finally:
        await host.drain()
        await host.close()
        await host.save()
    return dict(case=case['id'], mode=case['mode'], seed=case['seed'], policy=policy,
                terminal=result['terminal'], reason=result['reason'],
                actions=len(result['events']), elapsed_ns=result['elapsed_ns'])
