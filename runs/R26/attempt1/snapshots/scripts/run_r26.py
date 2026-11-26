"""R26: how much instrumentation does the safety benefit actually need?

Four levels, injected by the service itself:

* 0 - responses only (no permit, no lifecycle, no effect index);
* 1 - permit and manifest;
* 2 - permit, manifest and lifecycle receipts;
* 3 - full (adds the effect index).

Each level runs the same two faults with `clear`, `idem_retry` and `query_retry`,
idempotency off. The ladder measures what each increment buys.
"""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import r19_client as base

LEVELS = [0, 1, 2, 3]
POLICIES = ['clear', 'idem_retry', 'query_retry']
FAULTS = ['lost_return', 'late_commit']
FAULT_STEP = {'lost_return': 'attach', 'late_commit': 'commit'}
NAMES = ['docs/R26_minimal_retrofit_ladder_protocol.md', 'scripts/r26_service.py',
         'scripts/r19_client.py', 'scripts/run_r26.py', 'scripts/verify_r26.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value, exclusive=True):
    mode = 'x' if exclusive else 'w'
    with Path(path).open(mode, encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def wait_ready(directory, process, limit=30.0):
    deadline = time.time() + limit
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'service exited early with {process.returncode}')
        path = directory / 'ready.json'
        if path.exists():
            try:
                return json.loads(path.read_text(encoding='utf-8'))['base_url']
            except (json.JSONDecodeError, KeyError):
                pass
        time.sleep(0.05)
    raise RuntimeError('service did not become ready')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--seeds', default='0-9')
    parser.add_argument('--levels', default=','.join(str(item) for item in LEVELS))
    parser.add_argument('--policies', default=','.join(POLICIES))
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    levels = [int(item) for item in args.levels.split(',') if item]
    policies = [item for item in args.policies.split(',') if item]
    run_dir = ROOT / 'runs' / 'R26' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        destination = run_dir / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
        hashes[name] = sha(ROOT / name)
    save(run_dir / 'freeze.json', dict(
        levels=levels, policies=policies, seeds=seeds, faults=FAULTS,
        fault_step=FAULT_STEP, idempotency='off', lifecycle='faithful',
        query_mode='faithful', steps=base.STEPS, files=hashes,
        post_timeout_s=base.POST_TIMEOUT, get_timeout_s=base.GET_TIMEOUT,
        dispatch_jitter_s=base.JITTER, python=sys.executable,
        python_version=platform.python_version(), service='r26_service.py',
        target_calls_before_freeze=0, created_ns=time.time_ns()))
    save(run_dir / 'installation.json', dict(
        python=sys.executable, python_version=platform.python_version(),
        prefix=sys.prefix,
        versions={'clear-assurance': importlib.metadata.version('clear-assurance')}))
    results, failures = [], []
    for level in levels:
        config = f'L{level}'
        directory = run_dir / config
        directory.mkdir()
        save(directory / 'faults.json',
             {f'{kind}_S{seed}_{policy}': {FAULT_STEP[kind]: dict(
                 kind=kind, delay=base.LATE_DELAY)}
              for kind in FAULTS for seed in seeds for policy in policies},
             exclusive=False)
        (directory / 'idempotency').write_text('off', encoding='utf-8')
        (directory / 'lifecycle').write_text('faithful', encoding='utf-8')
        (directory / 'query_mode').write_text('faithful', encoding='utf-8')
        (directory / 'instrumentation').write_text(str(level), encoding='utf-8')
        log = (directory / 'service.log').open('w', encoding='utf-8')
        process = subprocess.Popen(
            [sys.executable, str(ROOT / 'scripts' / 'r26_service.py'),
             '--run-root', str(directory)],
            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
        try:
            base_url = wait_ready(directory, process)
            for kind in FAULTS:
                for policy in policies:
                    for seed in seeds:
                        workflow = f'{kind}_S{seed}_{policy}'
                        try:
                            client = base.Client(base_url)
                            result = base.run_workflow(client, workflow, policy,
                                                       kind, seed)
                            result.update(config=config, level=level, fault=kind,
                                          policy=policy, seed=seed, workflow=workflow)
                            results.append(result)
                        except BaseException as error:
                            failures.append(dict(workflow=workflow, config=config,
                                                 level=level, policy=policy,
                                                 fault=kind, seed=seed,
                                                 type=type(error).__name__,
                                                 message=str(error),
                                                 traceback=traceback.format_exc()))
            base.Client(base_url).stop()
        finally:
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            log.close()
        save(directory / 'service.json', dict(base_url=base_url, pid=process.pid,
                                              returncode=process.returncode,
                                              instrumentation=level))
    save(run_dir / 'completion.json', dict(
        levels=levels, configs=[f'L{level}' for level in levels],
        policies=policies, seeds=seeds, faults=FAULTS, tasks=results,
        failures=failures,
        sealed={path.relative_to(run_dir).as_posix(): sha(path)
                for path in run_dir.rglob('*')
                if path.is_file() and 'snapshots' not in path.parts
                and 'private' not in path.parts
                and not path.name.endswith('.sqlite')
                and path.name not in ('completion.json', 'service.log')}))


if __name__ == '__main__':
    main()
