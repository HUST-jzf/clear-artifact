"""Run R38: evidence-only CLEAR versus fence-ordered settlement."""
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
import r38_client

STEPS = r38_client.STEPS
FAULTS = ['late_effect', 'lost_before_commit']
POLICIES = {'faithful': ['clear', 'blind_retry', 'pause'],
            'absent': ['clear', 'clear_fenced', 'blind_retry', 'pause']}
CLOSURES = ['faithful', 'absent']
SEEDS = list(range(1, 21))


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


def task(run, closure, fault, policy, seed, python):
    workflow = f'{closure}_{fault}_{policy}_S{seed}'
    directory = run / f'{closure}_{fault}_{policy}_s{seed}'
    directory.mkdir()
    (directory / 'faults.json').write_text(
        json.dumps({workflow: {'attach': {'kind': fault, 'delay': 1.0}}}), encoding='utf-8')
    (directory / 'closure').write_text(closure, encoding='utf-8')
    process = subprocess.Popen([python, str(ROOT / 'scripts/r38_service.py'),
                                '--run-root', str(directory)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    started = time.perf_counter_ns()
    try:
        base = wait_ready(directory)
        client = r38_client.Client(base)
        epoch = int(client.permit(workflow).get('epoch', 1))
        for step in ['create', 'reserve']:
            client.legacy(workflow, step, 1, epoch)
        outcome = r38_client.POLICIES[policy](client, workflow, 'attach')
        if outcome['terminal'] == 'complete':
            epoch = int(client.permit(workflow).get('epoch', 1))
            for step in ['commit', 'notify']:
                client.legacy(workflow, step, 1, epoch)
        if fault == 'late_effect':
            time.sleep(0.8)
        client.stop()
    finally:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    stats = json.loads((directory / 'private' / 'stats.json').read_text(encoding='utf-8'))
    observed = stats.get(workflow, dict(steps={}, rejected=0))
    rows = {step: int(observed['steps'].get(step, {}).get('rows', 0)) for step in STEPS}
    stale = {step: int(observed['steps'].get(step, {}).get('stale', 0)) for step in STEPS}
    committed = {step: int(observed['steps'].get(step, {}).get('committed', 0))
                 for step in STEPS}
    provisional = {step: int(observed['steps'].get(step, {}).get('provisional', 0))
                   for step in STEPS}
    duplicates = sum(max(0, rows[step] - 1) for step in STEPS)
    completed = all(rows[step] >= 1 for step in STEPS)
    result = dict(closure=closure, fault=fault, policy=policy, seed=seed, workflow=workflow,
                  terminal=outcome['terminal'], reason=outcome['reason'],
                  rows=rows, stale=stale, committed=committed, provisional=provisional,
                  rejected=int(observed['rejected']), duplicates=duplicates,
                  completed=completed,
                  safe=completed and duplicates == 0 and sum(stale.values()) == 0,
                  elapsed_ns=time.perf_counter_ns() - started)
    save(directory / 'result.json', result)
    return dict(closure=closure, fault=fault, policy=policy, seed=seed,
                rows=rows['attach'], terminal=outcome['terminal'],
                completed=completed, rejected=result['rejected'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    run = ROOT / 'runs' / 'R38' / args.attempt
    run.mkdir(parents=True, exist_ok=False)
    names = ['docs/R38_fence_settlement_protocol.md', 'scripts/r38_service.py',
             'scripts/r38_client.py', 'scripts/run_r38.py', 'scripts/verify_r38.py',
             'scripts/r38_fence_check.py']
    hashes = {}
    for name in names:
        source, destination = ROOT / name, run / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    save(run / 'freeze.json', dict(files=hashes, faults=FAULTS, policies=POLICIES,
                                   seeds=SEEDS, target_calls_before_freeze=0,
                                   python=sys.executable,
                                   python_version=platform.python_version(),
                                   created_ns=time.time_ns()))
    tasks, failures = [], []
    for closure in CLOSURES:
        for fault in FAULTS:
            for policy in POLICIES[closure]:
                for seed in SEEDS:
                    try:
                        tasks.append(task(run, closure, fault, policy, seed, sys.executable))
                    except BaseException as error:
                        failures.append(dict(closure=closure, fault=fault, policy=policy,
                                             seed=seed, type=type(error).__name__,
                                             message=str(error),
                                             traceback=traceback.format_exc()))
    save(run / 'completion.json', dict(tasks=tasks, failures=failures))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
