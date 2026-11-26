"""R2 randomized fault campaign over the three R1 sources."""
import hashlib
import json
import os
import random
import time
from pathlib import Path

MODES = ['fail_before', 'lost_return', 'late_commit', 'query_unavailable', 'executor_lost']

try:
    from r1_native import Host as _MCPHost
except ImportError:
    _MCPHost = None
from r1_anyio import Host as _AnyIOHost
try:
    from r1_langchain import Host as _LangChainHost
except ImportError:
    _LangChainHost = None


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def parameters(mode, seed):
    rng = random.Random((seed + 1) * 1000003 + MODES.index(mode) * 7919)
    timeout = rng.uniform(0.05, 0.09)
    if mode == 'late_commit':
        gate = rng.uniform(0.10, 0.20)
        wait = gate + rng.uniform(0.06, 0.12)
    elif mode == 'lost_return':
        gate = rng.uniform(0.005, 0.025)
        wait = 0.15
    else:
        gate = 0.0
        wait = 0.15
    return dict(initial_timeout=timeout, gate=gate, wait_window=wait)


def route_for(mode):
    return dict(revision=1, mode='inline',
                outcome='fail' if mode == 'fail_before' else 'commit',
                delayed=mode in ('lost_return', 'late_commit'),
                abandon_on_cancel=False, delegated=False,
                closed_registration=mode != 'executor_lost',
                allowed=True, store='effects', idempotency=False, query_complete=True)


def configure(source, timeout, wait, gate):
    os.environ['R1_INITIAL_TIMEOUT'] = repr(timeout)
    os.environ['R1_WAIT_WINDOW'] = repr(wait)
    os.environ['R1_GATE_DELAY_S'] = repr(gate)
    if source == 'mcp':
        import r1_native
        r1_native.INITIAL_TIMEOUT = timeout
        r1_native.WAIT_WINDOW = wait
    else:
        import r1_anyio
        r1_anyio.INITIAL_TIMEOUT = timeout
        r1_anyio.WAIT_WINDOW = wait
        r1_anyio.GATE_DELAY_S = gate
        if source == 'langchain':
            import r1_langchain
            r1_langchain.INITIAL_TIMEOUT = timeout


class TransientQuery:
    query_fail_first = False

    async def call(self, tool, arguments):
        if tool == 'effects' and self.query_fail_first and not getattr(self, 'query_failed', False):
            self.query_failed = True
            self._count(tool, 'transient_error')
            return dict(state='unknown', complete=False, transient=True,
                        effect_namespace='effects',
                        operation_id=arguments.get('operation_id'),
                        intent=arguments.get('intent'), generation=1)
        return await super().call(tool, arguments)


def make_host(source, directory, route, transient):
    base = {'mcp': _MCPHost, 'anyio': _AnyIOHost, 'langchain': _LangChainHost}[source]
    if base is None:
        raise RuntimeError(f'source {source} unavailable in this environment')
    host = type('R2Host', (TransientQuery, base), {})(directory, route, None)
    host.query_fail_first = bool(transient)
    host.query_failed = False
    return host


async def task(run, source, case, policy):
    from r1_policies import run as control
    directory = run / f"S{case['seed']}_{case['mode']}_{policy}"
    params = parameters(case['mode'], case['seed'])
    configure(source, params['initial_timeout'], params['wait_window'], params['gate'])
    host = make_host(source, directory, route_for(case['mode']),
                     case['mode'] == 'query_unavailable')
    result = None
    try:
        await host.start()
        result = await control(host, policy)
        result.update(case=case['id'], mode=case['mode'], seed=case['seed'],
                      params=params, elapsed_ns=time.perf_counter_ns() - host.begin_ns)
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
