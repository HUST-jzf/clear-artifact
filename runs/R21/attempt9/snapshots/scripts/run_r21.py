"""R21: concurrent workflows against the ticket service."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import r19_client as base
import r21_client as r21

CONCURRENCY = [8, 32]
SEEDS = list(range(20))
FAULTS = ['lost_return', 'late_commit']
NAMES = ['docs/R21_concurrency_throughput_protocol.md', 'scripts/r21_service.py',
         'scripts/r19_client.py', 'scripts/r21_client.py', 'scripts/run_r21.py',
         'scripts/verify_r21.py']


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
    parser.add_argument('--seeds', default='0-19')
    parser.add_argument('--configs', default='')
    parser.add_argument('--policies', default=','.join(base.POLICIES))
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    policies = [item for item in args.policies.split(',') if item]
    configs = [dict(name=f'c{level}-{idem}', concurrency=level, idem=idem)
               for level in CONCURRENCY for idem in ('on', 'off')]
    if args.configs:
        wanted = set(item for item in args.configs.split(',') if item)
        configs = [item for item in configs if item['name'] in wanted]
    run_dir = ROOT / 'runs' / 'R21' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        source, destination = ROOT / name, run_dir / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    save(run_dir / 'freeze.json', dict(
        configs=[dict(name=item['name'], concurrency=item['concurrency'], idem=item['idem'])
                 for item in configs], seeds=seeds, policies=policies, faults=FAULTS,
        fault_step={'lost_return': 'attach', 'late_commit': 'commit'},
        steps=base.STEPS, files=hashes, post_timeout_s=r21.POST_TIMEOUT,
        read_timeout_s=r21.READ_TIMEOUT, late_delay_s=r21.LATE_DELAY,
        measure_timeout_s=r21.MEASURE_TIMEOUT, measure_attempts=r21.MEASURE_ATTEMPTS,
        dispatch_jitter_s=base.JITTER, python=sys.executable,
        python_version=platform.python_version(), service='r21_service.py faithful',
        target_calls_before_freeze=0, created_ns=time.time_ns()))
    save(run_dir / 'installation.json', dict(
        python=sys.executable, python_version=platform.python_version(),
        prefix=sys.prefix,
        versions={'clear-assurance': importlib.metadata.version('clear-assurance')}))
    results, failures, systems = [], [], []
    try:
        for config in configs:
            directory = run_dir / config['name']
            directory.mkdir()
            faults = {f'{kind}_S{seed}_{policy}': {'attach' if kind == 'lost_return' else 'commit':
                                                   dict(kind=kind, delay=r21.LATE_DELAY)}
                      for kind in FAULTS for seed in seeds for policy in policies}
            save(directory / 'faults.json', faults, exclusive=False)
            (directory / 'idempotency').write_text(config['idem'], encoding='utf-8')
            (directory / 'lifecycle').write_text('faithful', encoding='utf-8')
            (directory / 'query_mode').write_text('faithful', encoding='utf-8')
            log = (directory / 'service.log').open('w', encoding='utf-8')
            process = subprocess.Popen(
                [sys.executable, str(ROOT / 'scripts' / 'r21_service.py'),
                 '--run-root', str(directory)],
                cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
            try:
                base_url = wait_ready(directory, process)

                def job(kind, policy, seed):
                    workflow = f'{kind}_S{seed}_{policy}'
                    try:
                        client = r21.Client(base_url)
                        try:
                            result = base.run_workflow(client, workflow, policy, kind, seed)
                        finally:
                            client.close()
                        result.update(config=config['name'], campaign='concurrency',
                                      concurrency=config['concurrency'], idem=config['idem'],
                                      fault=kind)
                        return 'ok', result
                    except BaseException as error:
                        return 'error', dict(
                            config=config['name'], workflow=workflow, policy=policy,
                            fault=kind, seed=seed, type=type(error).__name__,
                            message=str(error), traceback=traceback.format_exc())

                jobs = [(kind, policy, seed) for kind in FAULTS
                        for policy in policies for seed in seeds]
                started = time.perf_counter_ns()
                with ThreadPoolExecutor(max_workers=config['concurrency']) as pool:
                    outcomes = list(pool.map(lambda item: job(*item), jobs))
                wall_ns = time.perf_counter_ns() - started
                for status, payload in outcomes:
                    if status == 'ok':
                        results.append(payload)
                    else:
                        failures.append(payload)
                latencies = [task['elapsed_ns'] / 1e6 for status, task in outcomes
                             if status == 'ok']
                systems.append(dict(
                    config=config['name'], concurrency=config['concurrency'],
                    idem=config['idem'], workflows=len(jobs), wall_s=round(wall_ns / 1e9, 3),
                    throughput=round(len(jobs) * 1e9 / wall_ns, 3),
                    p50_ms=round(percentile(latencies, 0.50), 2),
                    p95_ms=round(percentile(latencies, 0.95), 2),
                    failures=sum(1 for status, _ in outcomes if status == 'error')))
                client = base.Client(base_url)
                client.stop()
            finally:
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                log.close()
            save(directory / 'service.json', dict(
                base_url=base_url, pid=process.pid, returncode=process.returncode,
                concurrency=config['concurrency'], idempotency=config['idem']))
        save(run_dir / 'completion.json', dict(
            configs=[item['name'] for item in configs], seeds=seeds, policies=policies,
            faults=FAULTS, tasks=results, failures=failures, systems=systems,
            sealed={path.relative_to(run_dir).as_posix(): sha(path)
                    for path in run_dir.rglob('*')
                    if path.is_file() and 'snapshots' not in path.parts
                    and 'private' not in path.parts
                    and not path.name.endswith('.sqlite')
                    and path.name not in ('completion.json', 'service.log')}))
    except BaseException as error:
        save(run_dir / 'failure.json', dict(type=type(error).__name__, message=str(error),
                                            traceback=traceback.format_exc()))
        raise


if __name__ == '__main__':
    main()
