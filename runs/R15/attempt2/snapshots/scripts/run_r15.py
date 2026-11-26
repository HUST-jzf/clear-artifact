"""R15: five-step workflows against a real HTTP ticket service.

Freezes the protocol, starts one service process per idempotency configuration,
runs every workflow, and seals the recorded observations.
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
import r15_client as r15

CONFIGS = ['idem_on', 'idem_off']
SEEDS = list(range(20))
NAMES = ['docs/R15_end_to_end_workflow_protocol.md', 'scripts/r15_service.py',
         'scripts/r15_client.py', 'scripts/run_r15.py', 'scripts/verify_r15.py']


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
    parser.add_argument('--configs', default=','.join(CONFIGS))
    parser.add_argument('--policies', default=','.join(r15.POLICIES))
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    configs = [item for item in args.configs.split(',') if item]
    policies = [item for item in args.policies.split(',') if item]
    run_dir = ROOT / 'runs' / 'R15' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        source, destination = ROOT / name, run_dir / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    faults = {r15.workflow_id(kind, seed, policy):
              {r15.FAULT_STEP[kind]: dict(kind=kind, delay=r15.LATE_DELAY)}
              for kind in r15.FAULTS for seed in seeds for policy in policies}
    save(run_dir / 'freeze.json', dict(
        configs=configs, faults=r15.FAULTS, fault_step=r15.FAULT_STEP, seeds=seeds,
        policies=policies, steps=r15.STEPS, cases=len(faults), files=hashes,
        post_timeout_s=r15.POST_TIMEOUT, get_timeout_s=r15.GET_TIMEOUT,
        late_delay_s=r15.LATE_DELAY, dispatch_jitter_s=r15.JITTER,
        service_version=r15.SERVICE_VERSION, source=dict(r15.SOURCE),
        python=sys.executable, python_version=platform.python_version(),
        target_calls_before_freeze=0, created_ns=time.time_ns()))
    save(run_dir / 'installation.json', dict(
        python=sys.executable, python_version=platform.python_version(),
        prefix=sys.prefix,
        versions={'clear-assurance': importlib.metadata.version('clear-assurance')}))
    results, failures = [], []
    try:
        for config in configs:
            directory = run_dir / config
            directory.mkdir()
            save(directory / 'faults.json', faults, exclusive=False)
            (directory / 'idempotency').write_text(
                'on' if config == 'idem_on' else 'off', encoding='utf-8')
            log = (directory / 'service.log').open('w', encoding='utf-8')
            process = subprocess.Popen(
                [sys.executable, str(ROOT / 'scripts' / 'r15_service.py'),
                 '--run-root', str(directory)],
                cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
            try:
                base_url = wait_ready(directory, process)
                client = r15.Client(base_url)
                for kind in r15.FAULTS:
                    for policy in policies:
                        for seed in seeds:
                            workflow = r15.workflow_id(kind, seed, policy)
                            try:
                                result = r15.run_workflow(client, workflow, policy, kind, seed)
                                result['config'] = config
                                results.append(result)
                            except BaseException as error:
                                failures.append(dict(
                                    config=config, workflow=workflow, policy=policy,
                                    fault=kind, seed=seed, type=type(error).__name__,
                                    message=str(error), traceback=traceback.format_exc()))
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
                idempotency=config == 'idem_on'))
        save(run_dir / 'completion.json', dict(
            configs=configs, policies=policies, seeds=seeds, tasks=results,
            failures=failures, sealed={
                path.relative_to(run_dir).as_posix(): sha(path) for path in run_dir.rglob('*')
                if path.is_file() and 'snapshots' not in path.parts
                and 'private' not in path.parts and not path.name.endswith('.sqlite')
                and path.name not in ('completion.json', 'service.log')}))
    except BaseException as error:
        save(run_dir / 'failure.json', dict(type=type(error).__name__, message=str(error),
                                            traceback=traceback.format_exc()))
        raise


if __name__ == '__main__':
    main()
