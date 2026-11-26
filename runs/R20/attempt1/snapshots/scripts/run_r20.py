"""R20: multi-fault and seed-chosen fault placement campaign."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import random
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import r19_client as r19
import r20_client as r20

CAMPAIGNS = ['single_lost', 'single_late', 'double_lost']
SEEDS = list(range(20))
NAMES = ['docs/R20_multi_fault_random_position_protocol.md', 'scripts/r19_service.py',
         'scripts/r19_client.py', 'scripts/r20_client.py', 'scripts/run_r20.py',
         'scripts/verify_r20.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value, exclusive=True):
    mode = 'x' if exclusive else 'w'
    with Path(path).open(mode, encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def placements(campaign, seed):
    rng = random.Random((seed + 1) * 7919 + CAMPAIGNS.index(campaign) * 104729)
    if campaign == 'single_lost':
        return [[rng.randrange(len(r19.STEPS)), 'lost_return']]
    if campaign == 'single_late':
        return [[rng.randrange(len(r19.STEPS)), 'late_commit']]
    first, second = sorted(rng.sample(range(len(r19.STEPS)), 2))
    return [[first, 'lost_return'], [second, 'lost_return']]


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
    parser.add_argument('--campaigns', default=','.join(CAMPAIGNS))
    parser.add_argument('--configs', default='')
    parser.add_argument('--policies', default=','.join(r20.POLICIES))
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    campaigns = [item for item in args.campaigns.split(',') if item]
    policies = [item for item in args.policies.split(',') if item]
    configs = [dict(name=f'{campaign}-{idem}', campaign=campaign, idem=idem)
               for campaign in campaigns for idem in ('on', 'off')]
    if args.configs:
        wanted = set(item for item in args.configs.split(',') if item)
        configs = [item for item in configs if item['name'] in wanted]
    placement_map = {f'{campaign}:{seed}': placements(campaign, seed)
                     for campaign in campaigns for seed in seeds}
    run_dir = ROOT / 'runs' / 'R20' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        source, destination = ROOT / name, run_dir / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    save(run_dir / 'freeze.json', dict(
        configs=[item['name'] for item in configs], campaigns=campaigns,
        seeds=seeds, policies=policies, steps=r19.STEPS, files=hashes,
        placements=placement_map, post_timeout_s=r19.POST_TIMEOUT,
        get_timeout_s=r19.GET_TIMEOUT, late_delay_s=r19.LATE_DELAY,
        dispatch_jitter_s=r19.JITTER, python=sys.executable,
        python_version=platform.python_version(),
        target_calls_before_freeze=0, created_ns=time.time_ns()))
    save(run_dir / 'installation.json', dict(
        python=sys.executable, python_version=platform.python_version(),
        prefix=sys.prefix,
        versions={'clear-assurance': importlib.metadata.version('clear-assurance')}))
    results, failures = [], []
    try:
        for config in configs:
            directory = run_dir / config['name']
            directory.mkdir()
            faults = {}
            for seed in seeds:
                entries = placement_map[f"{config['campaign']}:{seed}"]
                step_map = {r19.STEPS[index]: dict(kind=kind, delay=r19.LATE_DELAY)
                            for index, kind in entries}
                for policy in policies:
                    faults[f"{config['campaign']}_S{seed}_{policy}"] = step_map
            save(directory / 'faults.json', faults, exclusive=False)
            (directory / 'idempotency').write_text(config['idem'], encoding='utf-8')
            (directory / 'lifecycle').write_text('faithful', encoding='utf-8')
            (directory / 'query_mode').write_text('faithful', encoding='utf-8')
            log = (directory / 'service.log').open('w', encoding='utf-8')
            process = subprocess.Popen(
                [sys.executable, str(ROOT / 'scripts' / 'r19_service.py'),
                 '--run-root', str(directory)],
                cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
            try:
                base_url = wait_ready(directory, process)
                client = r19.Client(base_url)
                for seed in seeds:
                    for policy in policies:
                        workflow = f"{config['campaign']}_S{seed}_{policy}"
                        try:
                            result = r20.run_workflow(
                                client, workflow, policy,
                                placement_map[f"{config['campaign']}:{seed}"], seed)
                            result.update(config=config['name'],
                                          campaign=config['campaign'],
                                          idem=config['idem'])
                            results.append(result)
                        except BaseException as error:
                            failures.append(dict(
                                config=config['name'], workflow=workflow, policy=policy,
                                seed=seed, type=type(error).__name__,
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
                idempotency=config['idem'], campaign=config['campaign']))
        save(run_dir / 'completion.json', dict(
            configs=[item['name'] for item in configs], campaigns=campaigns,
            seeds=seeds, policies=policies, tasks=results, failures=failures,
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
