"""R22: steady-state cost of the five policies on the ticket service (no faults).

R15-R21 report what CLEAR buys under faults; none of them report what it costs
when nothing goes wrong. Here no fault is injected: every policy should complete
all five steps with exactly one row, and the only question is how many HTTP calls
and how much latency CLEAR spends relative to the baselines.

Run serially over the WAL-configured `r21_service.py`, so the numbers are not
dominated by per-commit fsync or by queueing.
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
import r21_client as r21

POLICIES = list(base.POLICIES)
EXPECTED_CALLS = {'clear': 16, 'idem_retry': 11, 'query_retry': 11,
                  'reauth_retry': 11, 'pause': 11}
NAMES = ['docs/R22_no_fault_cost_protocol.md', 'scripts/r21_service.py',
         'scripts/r19_client.py', 'scripts/r21_client.py', 'scripts/run_r22.py',
         'scripts/verify_r22.py']


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


def percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--seeds', default='0-39')
    parser.add_argument('--policies', default=','.join(POLICIES))
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    policies = [item for item in args.policies.split(',') if item]
    run_dir = ROOT / 'runs' / 'R22' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        destination = run_dir / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
        hashes[name] = sha(ROOT / name)
    save(run_dir / 'freeze.json', dict(
        config='serial', policies=policies, seeds=seeds, faults=[],
        idempotency='on', lifecycle='faithful', query_mode='faithful',
        steps=base.STEPS, files=hashes, expected_http_calls=EXPECTED_CALLS,
        post_timeout_s=r21.POST_TIMEOUT, read_timeout_s=r21.READ_TIMEOUT,
        dispatch_jitter_s=base.JITTER, python=sys.executable,
        python_version=platform.python_version(), service='r21_service.py',
        target_calls_before_freeze=0, created_ns=time.time_ns()))
    save(run_dir / 'installation.json', dict(
        python=sys.executable, python_version=platform.python_version(),
        prefix=sys.prefix,
        versions={'clear-assurance': importlib.metadata.version('clear-assurance')}))
    directory = run_dir / 'serial'
    directory.mkdir()
    save(directory / 'faults.json', {}, exclusive=False)
    (directory / 'idempotency').write_text('on', encoding='utf-8')
    (directory / 'lifecycle').write_text('faithful', encoding='utf-8')
    (directory / 'query_mode').write_text('faithful', encoding='utf-8')
    results, failures = [], []
    log = (directory / 'service.log').open('w', encoding='utf-8')
    process = subprocess.Popen(
        [sys.executable, str(ROOT / 'scripts' / 'r21_service.py'),
         '--run-root', str(directory)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    try:
        base_url = wait_ready(directory, process)
        jobs = [(policy, seed) for policy in policies for seed in seeds]
        started = time.perf_counter_ns()
        for policy, seed in jobs:
            workflow = f'normal_S{seed}_{policy}'
            try:
                client = r21.Client(base_url)
                try:
                    result = base.run_workflow(client, workflow, policy,
                                               'lost_return', seed)
                finally:
                    client.close()
                result.update(config='serial', fault='none', policy=policy,
                              seed=seed, workflow=workflow)
                results.append(result)
            except BaseException as error:
                failures.append(dict(workflow=workflow, policy=policy, seed=seed,
                                     type=type(error).__name__, message=str(error),
                                     traceback=traceback.format_exc()))
        wall_ns = time.perf_counter_ns() - started
        latencies = [task['elapsed_ns'] / 1e6 for task in results]
        systems = [dict(
            config='serial', concurrency=1, workflows=len(jobs),
            wall_s=round(wall_ns / 1e9, 3),
            throughput=round(len(jobs) * 1e9 / wall_ns, 3),
            p50_ms=round(percentile(latencies, 0.50), 2),
            p95_ms=round(percentile(latencies, 0.95), 2), failures=len(failures))]
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
        concurrency=1, idempotency='on'))
    save(run_dir / 'completion.json', dict(
        configs=['serial'], policies=policies, seeds=seeds, faults=[],
        tasks=results, failures=failures, systems=systems,
        sealed={path.relative_to(run_dir).as_posix(): sha(path)
                for path in run_dir.rglob('*')
                if path.is_file() and 'snapshots' not in path.parts
                and 'private' not in path.parts
                and not path.name.endswith('.sqlite')
                and path.name not in ('completion.json', 'service.log')}))


if __name__ == '__main__':
    main()
