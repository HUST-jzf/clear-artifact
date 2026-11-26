"""Freeze and run R11: real subprocess crash and restart."""
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
import r11_host

POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']


def route(crash, **changes):
    body = dict(revision=1, mode='inline', outcome='commit', delayed=False,
                abandon_on_cancel=False, delegated=False, closed_registration=True,
                allowed=True, store='effects', idempotency=False, query_complete=True,
                crash=crash)
    body.update(changes)
    return body


CASES = [
    dict(id='crash_after_commit', route=route('after_commit'), patch=None),
    dict(id='crash_before_commit', route=route('before_commit'), patch=None),
    dict(id='crash_after_commit_revoke', route=route('after_commit'),
         patch={'allowed': False}),
    dict(id='crash_before_commit_revoke', route=route('before_commit'),
         patch={'allowed': False}),
    dict(id='crash_after_commit_no_query', route=route('after_commit', query_complete=False),
         patch=None),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def timing(seed):
    # deterministic jitter around the R1 calibration; the crash itself is marker-driven
    timeout = 0.05 + (seed % 10) * 0.004
    return timeout, 0.15


async def task(run, case, policy, seed):
    from r1_policies import run as control
    timeout, wait = timing(seed)
    r11_host.INITIAL_TIMEOUT = timeout
    r11_host.WAIT_WINDOW = wait
    directory = run / f"S{seed}_{case['id']}_{policy}"
    host = r11_host.Host(directory, case['route'], case['patch'])
    result = None
    try:
        await host.start()
        result = await control(host, policy)
        result.update(case=case['id'], policy=policy, seed=seed, elapsed_ns=time.perf_counter_ns() - host.begin_ns)
        save(directory / 'result.json', result)
    except BaseException as error:
        save(directory / 'failure.json', dict(type=type(error).__name__, message=str(error),
                                              traceback=traceback.format_exc()))
        raise
    finally:
        # R11 has no delayed commits; drain would only force an unnecessary restart.
        await host.close()
        await host.save()
    return dict(case=case['id'], policy=policy, seed=seed, terminal=result['terminal'],
                reason=result['reason'], actions=len(result['events']),
                elapsed_ns=result['elapsed_ns'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--seeds', default='0-19')
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    run_dir = ROOT / 'runs/R11' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    names = ['docs/R11_process_crash_protocol.md', 'scripts/r11_worker.py',
             'scripts/r11_host.py', 'scripts/run_r11.py', 'scripts/verify_r11.py',
             'scripts/r1_policies.py']
    hashes = {}
    for name in names:
        src, dest = ROOT / name, run_dir / 'snapshots' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        hashes[name] = sha(src)
    save(run_dir / 'freeze.json', dict(files=hashes, cases=CASES, policies=POLICIES,
         seeds=seeds, target_calls_before_freeze=0, python=sys.executable,
         python_version=platform.python_version(), created_ns=time.time_ns()))
    try:
        import anyio
        import clear_assurance
        versions = {name: importlib.metadata.version(name)
                    for name in ['clear-assurance', 'anyio']}
        assert versions['clear-assurance'] == '2.0.0'
        save(run_dir / 'installation.json', dict(versions=versions, prefix=sys.prefix,
             package=clear_assurance.__file__))
        results, failures = [], []
        for case in CASES:
            for policy in POLICIES:
                for seed in seeds:
                    try:
                        results.append(anyio.run(task, run_dir, case, policy, seed))
                    except BaseException as error:
                        failures.append(dict(case=case['id'], policy=policy, seed=seed,
                                             type=type(error).__name__, message=str(error),
                                             traceback=traceback.format_exc()))
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
