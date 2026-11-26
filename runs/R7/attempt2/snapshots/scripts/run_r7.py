"""Run R7 overhead: 6 conditions × 4 policies × 50 repetitions."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import r1_anyio
from r7_overhead import TimedHost

POLICIES = ['clear', 'idem_retry', 'query_retry', 'pause']
REPETITIONS = 50
r1_anyio.INITIAL_TIMEOUT = 0.06
r1_anyio.WAIT_WINDOW = 0.15
r1_anyio.GATE_DELAY_S = 0.08


def condition(name, patch=None, **changes):
    route = dict(revision=1, mode='inline', outcome='commit', delayed=False,
                 abandon_on_cancel=False, delegated=False, closed_registration=True,
                 allowed=True, store='effects', idempotency=False, query_complete=True)
    route.update(changes)
    return dict(id=name, route=route, patch=patch)


CASES = [
    condition('normal'),
    condition('fail_before', outcome='fail'),
    condition('lost_return'),
    condition('late_commit', delayed=True),
    condition('revoke', outcome='fail', patch={'allowed': False}),
    condition('closure_missing', closed_registration=False),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


async def task(run_dir, case, policy, repetition):
    from r1_policies import run as control
    directory = run_dir / f"R{repetition:02d}_{case['id']}_{policy}"
    host = TimedHost(directory, case['route'], case['patch'])
    result = None
    try:
        await host.start()
        host.timings.clear()
        host.counts.clear()
        started = time.perf_counter_ns()
        result = await control(host, policy)
        control_ns = time.perf_counter_ns() - started
        result.update(case=case['id'], policy=policy, repetition=repetition,
                      control_ns=control_ns, elapsed_ns=time.perf_counter_ns() - host.begin_ns)
        save(directory / 'result.json', result)
    except BaseException as error:
        save(directory / 'failure.json', dict(type=type(error).__name__, message=str(error),
                                              traceback=traceback.format_exc()))
        raise
    finally:
        await host.drain()
        await host.save()
    state = json.loads((directory / 'state.json').read_text(encoding='utf-8'))
    writes = state.get('writes', [])
    stale = [w for w in writes if int(w.get('attempt', 0)) > 1 and not w.get('allowed', True)]
    body = dict(case=case['id'], policy=policy, repetition=repetition,
                terminal=result['terminal'], reason=result['reason'],
                control_ns=control_ns, timings=dict(host.timings), counts=dict(host.counts),
                actions=len(result['events']), rows=len(writes),
                duplicate=len(writes) > 1, stale_new=len(stale),
                safe=result['terminal'] == 'complete' and len(writes) == 1 and not stale)
    save(directory / 'timings.json', body)
    return body


async def main_async(run_dir):
    results, failures = [], []
    for repetition in range(REPETITIONS):
        for case in CASES:
            for policy in POLICIES:
                try:
                    results.append(await task(run_dir, case, policy, repetition))
                except BaseException as error:
                    failures.append(dict(case=case['id'], policy=policy,
                                         repetition=repetition,
                                         type=type(error).__name__, message=str(error),
                                         traceback=traceback.format_exc()))
    return results, failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    run_dir = ROOT / 'runs/R7' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    names = ['docs/R7_overhead_protocol.md', 'scripts/r7_overhead.py',
             'scripts/run_r7.py', 'scripts/verify_r7.py', 'scripts/r1_policies.py',
             'scripts/r1_anyio.py']
    hashes = {}
    for name in names:
        src, dest = ROOT / name, run_dir / 'snapshots' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        hashes[name] = sha(src)
    save(run_dir / 'freeze.json', dict(files=hashes, cases=CASES, policies=POLICIES,
         repetitions=REPETITIONS, python=sys.executable,
         python_version=platform.python_version(), created_ns=time.time_ns()))
    try:
        import anyio
        import clear_assurance
        versions = {name: importlib.metadata.version(name)
                    for name in ['clear-assurance', 'anyio']}
        assert versions['clear-assurance'] == '2.0.0'
        save(run_dir / 'installation.json', dict(versions=versions, prefix=sys.prefix,
             package=clear_assurance.__file__, anyio=anyio.__file__))
        results, failures = anyio.run(main_async, run_dir)
        save(run_dir / 'completion.json', dict(tasks=results, failures=failures, sealed={
            path.relative_to(run_dir).as_posix(): sha(path) for path in run_dir.rglob('*')
            if path.is_file() and 'snapshots' not in path.parts
            and path.name != 'completion.json' and not path.name.endswith('.sqlite')}))
    except BaseException as error:
        save(run_dir / 'failure.json', dict(type=type(error).__name__, message=str(error),
                                            traceback=traceback.format_exc()))
        raise


if __name__ == '__main__':
    main()
