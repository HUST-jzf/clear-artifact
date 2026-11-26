"""R31: does the receipt binding survive a cross-tenant forgery?

The service answers `/effects` with the first receipt found in *another*
workflow's database (`query=forged_tenant`), rewriting only `root` and `op`. The
receipt's `operation_id` still names the donor. A client that reads `state` alone
accepts it and skips the step; a client that checks the binding does not.

One donor workflow runs first so that every measured workflow has a receipt to be
offered.
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

POLICIES = list(base.POLICIES)
FAULT = 'lost_before_commit'
FAULT_STEP = 'attach'
NAMES = ['docs/R31_cross_tenant_binding_protocol.md', 'scripts/r31_service.py',
         'scripts/r19_client.py', 'scripts/run_r31.py', 'scripts/verify_r31.py']


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
    parser.add_argument('--seeds', default='0-19')
    parser.add_argument('--policies', default=','.join(POLICIES))
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    policies = [item for item in args.policies.split(',') if item]
    run_dir = ROOT / 'runs' / 'R31' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        destination = run_dir / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
        hashes[name] = sha(ROOT / name)
    save(run_dir / 'freeze.json', dict(
        config='tenant', policies=policies, seeds=seeds, fault=FAULT,
        fault_step=FAULT_STEP, idempotency='on', lifecycle='faithful',
        query_mode='forged_tenant', donor='donor', steps=base.STEPS,
        files=hashes, post_timeout_s=base.POST_TIMEOUT,
        get_timeout_s=base.GET_TIMEOUT, dispatch_jitter_s=base.JITTER,
        python=sys.executable, python_version=platform.python_version(),
        service='r31_service.py', target_calls_before_freeze=0,
        created_ns=time.time_ns()))
    save(run_dir / 'installation.json', dict(
        python=sys.executable, python_version=platform.python_version(),
        prefix=sys.prefix,
        versions={'clear-assurance': importlib.metadata.version('clear-assurance')}))
    directory = run_dir / 'tenant'
    directory.mkdir()
    save(directory / 'faults.json',
         {f'tenant_S{seed}_{policy}': {FAULT_STEP: dict(kind=FAULT)}
          for seed in seeds for policy in policies}, exclusive=False)
    (directory / 'idempotency').write_text('on', encoding='utf-8')
    (directory / 'lifecycle').write_text('faithful', encoding='utf-8')
    (directory / 'query_mode').write_text('forged_tenant', encoding='utf-8')
    results, failures = [], []
    log = (directory / 'service.log').open('w', encoding='utf-8')
    process = subprocess.Popen(
        [sys.executable, str(ROOT / 'scripts' / 'r31_service.py'),
         '--run-root', str(directory)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    try:
        base_url = wait_ready(directory, process)
        donor = base.run_workflow(base.Client(base_url), 'donor', 'clear',
                                  'lost_return', 0)
        donor.update(config='tenant', policy='donor', workflow='donor',
                     seed=None, fault='none')
        results.append(donor)
        for policy in policies:
            for seed in seeds:
                workflow = f'tenant_S{seed}_{policy}'
                try:
                    result = base.run_workflow(base.Client(base_url), workflow,
                                               policy, FAULT, seed)
                    result.update(config='tenant', fault=FAULT, policy=policy,
                                  seed=seed, workflow=workflow)
                    results.append(result)
                except BaseException as error:
                    failures.append(dict(workflow=workflow, policy=policy, seed=seed,
                                         type=type(error).__name__, message=str(error),
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
                                          query_mode='forged_tenant'))
    save(run_dir / 'completion.json', dict(
        configs=['tenant'], policies=policies, seeds=seeds, fault=FAULT,
        donor='donor', tasks=results, failures=failures,
        sealed={path.relative_to(run_dir).as_posix(): sha(path)
                for path in run_dir.rglob('*')
                if path.is_file() and 'snapshots' not in path.parts
                and 'private' not in path.parts
                and not path.name.endswith('.sqlite')
                and path.name not in ('completion.json', 'service.log')}))


if __name__ == '__main__':
    main()
