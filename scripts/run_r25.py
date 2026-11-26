"""R25: does the discriminating matrix survive a different domain?

Same controller, same five policies, same two faults, but the workflow is
`authorize -> capture -> settle -> notify` and the fault lands on `capture`, the
step that moves money. Every capture row is a charge, so the interesting metric
is the number of double-charged workflows, not the number of rows.
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
import r25_client as r25

POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']
FAULTS = ['lost_return', 'late_commit']
FAULT_STEP = {'lost_return': 'capture', 'late_commit': 'capture'}
NAMES = ['docs/R25_payment_domain_protocol.md', 'scripts/r25_service.py',
         'scripts/r19_client.py', 'scripts/r25_client.py', 'scripts/run_r25.py',
         'scripts/verify_r25.py']


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
    run_dir = ROOT / 'runs' / 'R25' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        destination = run_dir / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
        hashes[name] = sha(ROOT / name)
    save(run_dir / 'freeze.json', dict(
        domain='payments', steps=r25.STEPS, policies=policies, seeds=seeds,
        faults=FAULTS, fault_step=FAULT_STEP, idempotency=['on', 'off'],
        lifecycle='faithful', query_mode='faithful', charge=r25.CHARGE,
        files=hashes, post_timeout_s=base.POST_TIMEOUT,
        get_timeout_s=base.GET_TIMEOUT, dispatch_jitter_s=base.JITTER,
        python=sys.executable, python_version=platform.python_version(),
        service='r25_service.py', target_calls_before_freeze=0,
        created_ns=time.time_ns()))
    save(run_dir / 'installation.json', dict(
        python=sys.executable, python_version=platform.python_version(),
        prefix=sys.prefix,
        versions={'clear-assurance': importlib.metadata.version('clear-assurance')}))
    results, failures = [], []
    for idem in ['on', 'off']:
        config = f'idem_{idem}'
        directory = run_dir / config
        directory.mkdir()
        save(directory / 'faults.json',
             {f'{kind}_S{seed}_{policy}': {FAULT_STEP[kind]: dict(
                 kind=kind, delay=base.LATE_DELAY)}
              for kind in FAULTS for seed in seeds for policy in policies},
             exclusive=False)
        (directory / 'idempotency').write_text(idem, encoding='utf-8')
        (directory / 'lifecycle').write_text('faithful', encoding='utf-8')
        (directory / 'query_mode').write_text('faithful', encoding='utf-8')
        log = (directory / 'service.log').open('w', encoding='utf-8')
        process = subprocess.Popen(
            [sys.executable, str(ROOT / 'scripts' / 'r25_service.py'),
             '--run-root', str(directory)],
            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
        try:
            base_url = wait_ready(directory, process)
            for kind in FAULTS:
                for policy in policies:
                    for seed in seeds:
                        workflow = f'{kind}_S{seed}_{policy}'
                        try:
                            client = r25.Client(base_url)
                            result = r25.run_workflow(client, workflow, policy,
                                                      kind, seed)
                            ledger = client.ledger(workflow).get('body', {})
                            result.update(config=config, idempotency=idem, fault=kind,
                                          policy=policy, seed=seed, workflow=workflow,
                                          captured=int(ledger.get('captured', 0)),
                                          captures=int(ledger.get('captures', 0)),
                                          double_charge=int(
                                              ledger.get('captured', 0)) > r25.CHARGE)
                            results.append(result)
                        except BaseException as error:
                            failures.append(dict(workflow=workflow, config=config,
                                                 policy=policy, fault=kind, seed=seed,
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
                                              idempotency=idem, domain='payments'))
    save(run_dir / 'completion.json', dict(
        domain='payments', steps=r25.STEPS, configs=[f'idem_{x}' for x in ('on', 'off')],
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
