"""Run R35: CLEAR and verify_retry on identical evidence."""
import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import r35_client

STEPS = r35_client.STEPS
CONDITIONS = ['lost_return', 'lost_before_commit', 'revoke_race']
POLICIES = ['clear', 'verify_retry']
SEEDS = list(range(1, 21))
FAULT_KIND = {'lost_return': 'lost_return', 'lost_before_commit': 'lost_before_commit',
              'revoke_race': 'lost_before_commit'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def wait_ready(directory, timeout=10.0):
    path = directory / 'ready.json'
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding='utf-8'))['base_url']
            except (ValueError, KeyError):
                pass
        time.sleep(0.02)
    raise RuntimeError('service not ready')


def task(run, condition, policy, seed, python):
    workflow = f'{condition}_{policy}_S{seed}'
    directory = run / f'{condition}_{policy}_s{seed}'
    directory.mkdir()
    (directory / 'faults.json').write_text(
        json.dumps({workflow: {'attach': {'kind': FAULT_KIND[condition]}}}),
        encoding='utf-8')
    process = subprocess.Popen([python, str(ROOT / 'scripts/r35_service.py'),
                                '--run-root', str(directory)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    started = time.perf_counter_ns()
    try:
        base = wait_ready(directory)
        client = r35_client.Client(base)
        epoch = int(client.permit(workflow).get('epoch', 1))
        for step in ['create', 'reserve']:
            client.append(workflow, step, 1, epoch)
        client.append(workflow, 'attach', 1, epoch)
        if condition == 'revoke_race':
            r35_client.arm_revoke(client, workflow)
        outcome = r35_client.recover(client, workflow, 'attach', policy)
        if outcome['terminal'] == 'complete':
            epoch = int(client.permit(workflow).get('epoch', 1))
            for step in ['commit', 'notify']:
                client.append(workflow, step, 1, epoch)
        client.stop()
    finally:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    stats = json.loads((directory / 'private' / 'stats.json').read_text(encoding='utf-8'))
    observed = stats.get(workflow, {})
    rows = {step: int(observed.get(step, {}).get('rows', 0)) for step in STEPS}
    stale = {step: int(observed.get(step, {}).get('stale', 0)) for step in STEPS}
    duplicates = sum(max(0, rows[step] - 1) for step in STEPS)
    completed = all(rows[step] >= 1 for step in STEPS)
    result = dict(condition=condition, policy=policy, seed=seed, workflow=workflow,
                  terminal=outcome['terminal'], reason=outcome['reason'],
                  events=outcome['events'], rows=rows, stale=stale,
                  duplicates=duplicates, completed=completed,
                  safe=completed and duplicates == 0 and sum(stale.values()) == 0,
                  writes=outcome['writes'], elapsed_ns=time.perf_counter_ns() - started)
    save(directory / 'result.json', result)
    return dict(condition=condition, policy=policy, seed=seed,
                rows=rows['attach'], stale=stale['attach'], completed=completed,
                terminal=outcome['terminal'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    run = ROOT / 'runs' / 'R35' / args.attempt
    run.mkdir(parents=True, exist_ok=False)
    names = ['docs/R35_same_evidence_baseline_protocol.md', 'scripts/r35_service.py',
             'scripts/r35_client.py', 'scripts/run_r35.py', 'scripts/verify_r35.py',
             'scripts/r34_client.py']
    hashes = {}
    for name in names:
        source, destination = ROOT / name, run / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    save(run / 'freeze.json', dict(files=hashes, conditions=CONDITIONS,
                                   policies=POLICIES, seeds=SEEDS,
                                   target_calls_before_freeze=0, python=sys.executable,
                                   python_version=platform.python_version(),
                                   created_ns=time.time_ns()))
    tasks, failures = [], []
    for condition in CONDITIONS:
        for policy in POLICIES:
            for seed in SEEDS:
                try:
                    tasks.append(task(run, condition, policy, seed, sys.executable))
                except BaseException as error:
                    failures.append(dict(condition=condition, policy=policy, seed=seed,
                                         type=type(error).__name__, message=str(error),
                                         traceback=traceback.format_exc()))
    save(run / 'completion.json', dict(tasks=tasks, failures=failures))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
