"""Freeze and run R1 capability-space pilot on the AnyIO source."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def cases():
    out = []
    for idem in [0, 1]:
        for query in [0, 1]:
            for closure in [0, 1]:
                for change in ['none', 'revoke']:
                    for fault in ['fail', 'lost', 'late']:
                        name = f'I{idem}Q{query}C{closure}G{change}F{fault}'
                        route = dict(revision=1, mode='inline',
                                     outcome='fail' if fault == 'fail' else 'commit',
                                     delayed=fault == 'late', abandon_on_cancel=False,
                                     delegated=False, closed_registration=bool(closure),
                                     allowed=True, store='effects', idempotency=bool(idem),
                                     query_complete=bool(query))
                        out.append(dict(id=name, route=route,
                                        patch={'allowed': False} if change == 'revoke' else None,
                                        factors=dict(idempotency=idem, query_complete=query,
                                                     closure=closure, change=change, fault=fault)))
    return out


async def task(run, case, policy):
    from r1_anyio import Host, save as host_save
    from r1_policies import run as control
    host = Host(run / (case['id'] + '_' + policy), case['route'], case['patch'])
    result = None
    try:
        await host.start()
        result = await control(host, policy)
        result.update(case=case['id'], elapsed_ns=time.perf_counter_ns() - host.begin_ns)
        host_save(host.directory / 'result.json', result)
    except BaseException as error:
        save(host.directory / 'failure.json', dict(type=type(error).__name__, message=str(error),
                                                   traceback=traceback.format_exc()))
        raise
    finally:
        await host.drain()
        await host.close()
        await host.save()
    value = dict(case=case['id'], policy=policy, terminal=result['terminal'],
                 reason=result['reason'], actions=len(result['events']),
                 elapsed_ns=result['elapsed_ns'])
    print(json.dumps(value), flush=True)
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    run = ROOT / 'runs/R1_anyio' / args.attempt
    run.mkdir(parents=True, exist_ok=False)
    names = ['scripts/run_r1_anyio.py', 'scripts/r1_anyio.py', 'scripts/r1_policies.py',
             'scripts/verify_r1.py', 'docs/R1_capability_space_preregistration.md']
    hashes = {}
    for name in names:
        source, dest = ROOT / name, run / 'snapshots' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    config = cases()
    save(run / 'freeze.json', dict(files=hashes, cases=config, policies=POLICIES,
         seeds=[int(os.environ.get('R1_SEED', '0'))], budget=4,
         initial_timeout_s=float(os.environ.get('R1_INITIAL_TIMEOUT', '.06')),
         wait_window_s=float(os.environ.get('R1_WAIT_WINDOW', '.15')),
         late_gate_s=float(os.environ.get('R1_GATE_DELAY_S', '.08')),
         target_calls_before_freeze=0, python=sys.executable,
         python_version=platform.python_version(), created_ns=time.time_ns()))
    try:
        import anyio
        import anyio._backends._asyncio as anyio_asyncio
        import clear_assurance
        versions = {name: importlib.metadata.version(name)
                    for name in ['clear-assurance', 'anyio']}
        assert versions['clear-assurance'] == '2.0.0'
        modules = [('clear_assurance.core', __import__('clear_assurance.core', fromlist=['x'])),
                   ('anyio._backends._asyncio', anyio_asyncio)]
        save(run / 'installation.json', dict(versions=versions, prefix=sys.prefix,
             package=clear_assurance.__file__,
             modules={name: dict(path=module.__file__, sha256=sha(Path(module.__file__)))
                      for name, module in modules}))
        results, failures = [], []
        for case in config:
            for policy in POLICIES:
                try:
                    results.append(anyio.run(task, run, case, policy))
                except BaseException as error:
                    failures.append(dict(case=case['id'], policy=policy,
                                         type=type(error).__name__, message=str(error)))
        save(run / 'completion.json', dict(tasks=results, failures=failures, sealed={
            path.relative_to(run).as_posix(): sha(path) for path in run.rglob('*')
            if path.is_file() and 'snapshots' not in path.parts and path.name != 'completion.json'}))
    except BaseException as error:
        save(run / 'failure.json', dict(type=type(error).__name__, message=str(error),
                                        traceback=traceback.format_exc()))
        raise


if __name__ == '__main__':
    main()
