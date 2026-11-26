"""R19: evidence redundancy (2x3) and forged-receipt campaigns."""
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
import r19_client as r19

REDUNDANCY_SEEDS = list(range(10))
FORGED_SEEDS = list(range(20))
REDUNDANCY_FAULTS = ['lost_return', 'late_commit']
FORGED_FAULTS = ['lost_before_commit']
NAMES = ['docs/R19_evidence_redundancy_binding_protocol.md', 'scripts/r19_service.py',
         'scripts/r19_client.py', 'scripts/run_r19.py', 'scripts/verify_r19.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value, exclusive=True):
    mode = 'x' if exclusive else 'w'
    with Path(path).open(mode, encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def configs():
    items = []
    for idem in ('on', 'off'):
        for lifecycle in ('faithful', 'lost'):
            for query in ('faithful', 'stale', 'unavailable'):
                items.append(dict(idem=idem, lifecycle=lifecycle, query=query,
                                  name=f'{idem}-{lifecycle}-{query}',
                                  campaign='redundancy', seeds=REDUNDANCY_SEEDS,
                                  faults=REDUNDANCY_FAULTS))
    for idem in ('on', 'off'):
        for lifecycle in ('faithful', 'lost'):
            items.append(dict(idem=idem, lifecycle=lifecycle, query='forged',
                              name=f'{idem}-{lifecycle}-forged',
                              campaign='forged', seeds=FORGED_SEEDS,
                              faults=FORGED_FAULTS))
    return items


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
    parser.add_argument('--campaigns', default='redundancy,forged')
    parser.add_argument('--seeds', default='')
    parser.add_argument('--configs', default='')
    parser.add_argument('--policies', default=','.join(r19.POLICIES))
    args = parser.parse_args()
    wanted_campaigns = set(item for item in args.campaigns.split(',') if item)
    wanted_configs = set(item for item in args.configs.split(',') if item)
    policies = [item for item in args.policies.split(',') if item]
    items = [item for item in configs() if item['campaign'] in wanted_campaigns
             and (not wanted_configs or item['name'] in wanted_configs)]
    if args.seeds:
        if '-' in args.seeds:
            low, high = args.seeds.split('-')
            overridden = list(range(int(low), int(high) + 1))
        else:
            overridden = [int(item) for item in args.seeds.split(',') if item]
        for item in items:
            item['seeds'] = overridden
    run_dir = ROOT / 'runs' / 'R19' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        source, destination = ROOT / name, run_dir / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    save(run_dir / 'freeze.json', dict(
        configs=[dict(name=item['name'], idem=item['idem'], lifecycle=item['lifecycle'],
                      query=item['query'], campaign=item['campaign'],
                      seeds=item['seeds'], faults=item['faults']) for item in items],
        capabilities=dict(idempotency=['on', 'off'],
                          lifecycle=['faithful', 'lost'],
                          query=['faithful', 'stale', 'unavailable', 'forged']),
        steps=r19.STEPS, policies=policies, files=hashes,
        post_timeout_s=r19.POST_TIMEOUT, get_timeout_s=r19.GET_TIMEOUT,
        late_delay_s=r19.LATE_DELAY, dispatch_jitter_s=r19.JITTER,
        service_version=r19.SERVICE_VERSION, source=dict(r19.SOURCE),
        python=sys.executable, python_version=platform.python_version(),
        target_calls_before_freeze=0, created_ns=time.time_ns()))
    save(run_dir / 'installation.json', dict(
        python=sys.executable, python_version=platform.python_version(),
        prefix=sys.prefix,
        versions={'clear-assurance': importlib.metadata.version('clear-assurance')}))
    results, failures = [], []
    try:
        for item in items:
            directory = run_dir / item['name']
            directory.mkdir()
            faults = {r19.workflow_id(kind, seed, policy):
                      {r19.FAULT_STEP[kind]: dict(kind=kind, delay=r19.LATE_DELAY)}
                      for kind in item['faults'] for seed in item['seeds']
                      for policy in policies}
            save(directory / 'faults.json', faults, exclusive=False)
            (directory / 'idempotency').write_text(item['idem'], encoding='utf-8')
            (directory / 'lifecycle').write_text(item['lifecycle'], encoding='utf-8')
            (directory / 'query_mode').write_text(item['query'], encoding='utf-8')
            log = (directory / 'service.log').open('w', encoding='utf-8')
            process = subprocess.Popen(
                [sys.executable, str(ROOT / 'scripts' / 'r19_service.py'),
                 '--run-root', str(directory)],
                cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
            try:
                base_url = wait_ready(directory, process)
                client = r19.Client(base_url)
                for kind in item['faults']:
                    for policy in policies:
                        for seed in item['seeds']:
                            workflow = r19.workflow_id(kind, seed, policy)
                            try:
                                result = r19.run_workflow(client, workflow, policy, kind, seed)
                                result.update(config=item['name'],
                                              campaign=item['campaign'],
                                              idem=item['idem'],
                                              lifecycle=item['lifecycle'],
                                              query=item['query'])
                                results.append(result)
                            except BaseException as error:
                                failures.append(dict(
                                    config=item['name'], workflow=workflow, policy=policy,
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
                idempotency=item['idem'], lifecycle=item['lifecycle'],
                query=item['query'], campaign=item['campaign']))
        save(run_dir / 'completion.json', dict(
            configs=[item['name'] for item in items], policies=policies,
            seeds={item['name']: item['seeds'] for item in items}, tasks=results,
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
