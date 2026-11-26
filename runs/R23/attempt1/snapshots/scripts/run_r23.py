"""R23: does idempotency survive a key that is regenerated on retry?

Same service, same faults, same controller code as R19. The only difference is
whether the retry reuses the key of the first attempt:

* `idem_retry`   - one key per logical step, reused on retry (the favourable case);
* `idem_fresh`   - one key per attempt (what a host that rebuilds the tool call does);
* `clear`, `pause` - references.

The service keeps `idempotency=on`, so any duplicate under `idem_fresh` is caused
by key instability alone, not by a missing capability.
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
import r23_client as r23

POLICIES = ['clear', 'idem_retry', 'idem_fresh', 'pause']
FAULTS = ['lost_return', 'late_commit']
FAULT_STEP = {'lost_return': 'attach', 'late_commit': 'commit'}
NAMES = ['docs/R23_idempotency_key_stability_protocol.md', 'scripts/r19_service.py',
         'scripts/r19_client.py', 'scripts/r23_client.py', 'scripts/run_r23.py',
         'scripts/verify_r23.py']


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
            return json.loads(path.read_text(encoding='utf-8'))['base_url']
        time.sleep(0.05)
    raise RuntimeError('service did not become ready')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--seeds', default='0-19')
    parser.add_argument('--policies', default=','.join(POLICIES))
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    policies = [item for item in args.policies.split(',') if item]
    run_dir = ROOT / 'runs' / 'R23' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        destination = run_dir / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
        hashes[name] = sha(ROOT / name)
    save(run_dir / 'freeze.json', dict(
        config='idem_on', policies=policies, seeds=seeds, faults=FAULTS,
        fault_step=FAULT_STEP, idempotency='on', lifecycle='faithful',
        query_mode='faithful', key_scope={'idem_retry': 'per_step',
                                          'idem_fresh': 'per_attempt'},
        steps=base.STEPS, files=hashes, post_timeout_s=base.POST_TIMEOUT,
        get_timeout_s=base.GET_TIMEOUT, late_delay_s=base.LATE_DELAY,
        dispatch_jitter_s=base.JITTER, python=sys.executable,
        python_version=platform.python_version(), service='r19_service.py faithful',
        target_calls_before_freeze=0, created_ns=time.time_ns()))
    save(run_dir / 'installation.json', dict(
        python=sys.executable, python_version=platform.python_version(),
        prefix=sys.prefix,
        versions={'clear-assurance': importlib.metadata.version('clear-assurance')}))
    directory = run_dir / 'idem_on'
    directory.mkdir()
    faults = {f'{kind}_S{seed}_{policy}': {FAULT_STEP[kind]:
                                           dict(kind=kind, delay=base.LATE_DELAY)}
              for kind in FAULTS for seed in seeds for policy in policies}
    save(directory / 'faults.json', faults, exclusive=False)
    (directory / 'idempotency').write_text('on', encoding='utf-8')
    (directory / 'lifecycle').write_text('faithful', encoding='utf-8')
    (directory / 'query_mode').write_text('faithful', encoding='utf-8')
    results, failures = [], []
    wall_ns = 0
    log = (directory / 'service.log').open('w', encoding='utf-8')
    process = subprocess.Popen(
        [sys.executable, str(ROOT / 'scripts' / 'r19_service.py'),
         '--run-root', str(directory)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    try:
        base_url = wait_ready(directory, process)
        started = time.perf_counter_ns()
        for kind in FAULTS:
            for policy in policies:
                for seed in seeds:
                    workflow = f'{kind}_S{seed}_{policy}'
                    try:
                        client = r23.Client(base_url,
                                            fresh_keys=(policy == 'idem_fresh'))
                        controller = 'idem_retry' if policy == 'idem_fresh' else policy
                        result = base.run_workflow(client, workflow, controller,
                                                   kind, seed)
                        result.update(policy=policy, config='idem_on', fault=kind,
                                      seed=seed, workflow=workflow)
                        results.append(result)
                    except BaseException as error:
                        failures.append(dict(workflow=workflow, policy=policy,
                                             fault=kind, seed=seed,
                                             type=type(error).__name__,
                                             message=str(error),
                                             traceback=traceback.format_exc()))
        wall_ns = time.perf_counter_ns() - started
        base.Client(base_url).stop()
    finally:
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()
    save(directory / 'service.json', dict(
        base_url=base_url, pid=process.pid, returncode=process.returncode,
        idempotency='on'))
    save(run_dir / 'completion.json', dict(
        configs=['idem_on'], policies=policies, seeds=seeds, faults=FAULTS,
        tasks=results, failures=failures,
        wall_s=round(wall_ns / 1e9, 3),
        sealed={path.relative_to(run_dir).as_posix(): sha(path)
                for path in run_dir.rglob('*')
                if path.is_file() and 'snapshots' not in path.parts
                and 'private' not in path.parts
                and not path.name.endswith('.sqlite')
                and path.name not in ('completion.json', 'service.log')}))


if __name__ == '__main__':
    main()
