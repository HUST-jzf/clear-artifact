"""R44: equal-capability comparison of fence settlement and atomic key dedup.

Scenario A (recovery under fault): five steps, one fault on `attach`, three
mechanisms (`fenced`, `dedup_versioned`, `dedup_fresh`) over three fault kinds.

Scenario B (binding change): an effect is committed for seat 12A, then the
intent changes to 14C.  `fenced` and `dedup_versioned` write a second binding;
`dedup_unversioned` reuses one key per step and therefore reports completion
while the 14C effect was never written.
"""
import argparse
import hashlib
import json
import platform
import sqlite3
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import r44_client

STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
FAULTS = ['lost_return', 'late_effect', 'lost_before_commit']
POLICIES_A = ['fenced', 'dedup_versioned', 'dedup_fresh']
POLICIES_B = ['fenced', 'dedup_versioned', 'dedup_unversioned']
SEEDS_A = list(range(1, 21))
SEEDS_B = list(range(1, 7))
NAMES = ['docs/R44_equal_capability_protocol.md', 'scripts/r44_service.py',
         'scripts/r44_client.py', 'scripts/run_r44.py', 'scripts/verify_r44.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8')


def logical_bytes(directory):
    """Logical SQLite size (page_count * page_size), excluding WAL and freelist noise."""
    total = 0
    for path in (directory / 'private').glob('*.sqlite'):
        db = sqlite3.connect(path)
        try:
            total += int(db.execute('pragma page_count').fetchone()[0]) * \
                int(db.execute('pragma page_size').fetchone()[0])
        finally:
            db.close()
    return total


def wait_ready(directory, process, limit=30.0):
    deadline = time.time() + limit
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'service exited with {process.returncode}')
        path = directory / 'ready.json'
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))['base_url']
        time.sleep(0.02)
    raise RuntimeError('service did not become ready')


def key_of(mode, workflow, step, intent, version, attempt=None):
    if mode == 'unversioned':
        return f'{workflow}:{step}'
    base = f'{workflow}:{step}:{intent}:{version}'
    return base if attempt is None else f'{base}:{attempt}'


def run_steps(client, workflow, policy, version, fault_step='attach'):
    epoch = int(client.permit(workflow).get('epoch', 1))
    outcomes = {}
    for step in STEPS:
        intent = 'ticket:' + step
        op = f'{workflow}:{step}'
        if policy == 'fenced':
            outcome = r44_client.fenced(client, workflow, op, step, intent)
        else:
            mode = 'fresh' if policy == 'dedup_fresh' else 'versioned'
            key = key_of(mode, workflow, step, intent, version)
            outcome = r44_client.dedup(client, workflow, op, step, intent, key,
                                       fresh=(mode == 'fresh'))
        outcomes[step] = outcome
        if outcome['terminal'] != 'complete':
            break
    return epoch, outcomes


def task_a(run, fault, policy, seed, python):
    workflow = f'A_{fault}_{policy}_S{seed}'
    directory = run / 'A' / f'{fault}_{policy}_s{seed}'
    directory.mkdir(parents=True)
    (directory / 'faults.json').write_text(
        json.dumps({workflow: {'attach': {'kind': fault, 'delay': 1.0}}}), encoding='utf-8')
    (directory / 'closure').write_text('faithful', encoding='utf-8')
    capability = 'fenced' if policy == 'fenced' else 'dedup'
    process = subprocess.Popen([python, str(ROOT / 'scripts/r44_service.py'),
                                '--run-root', str(directory),
                                '--capability', capability],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    started = time.perf_counter_ns()
    try:
        base = wait_ready(directory, process)
        client = r44_client.Client(base)
        version = client.manifest().get('version', '')
        epoch, outcomes = run_steps(client, workflow, policy, version)
        if fault == 'late_effect':
            time.sleep(0.8)
        client.stop()
        calls = client.calls
    finally:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    elapsed = time.perf_counter_ns() - started
    stats = json.loads((directory / 'private' / 'stats.json').read_text(encoding='utf-8'))
    observed = stats.get(workflow, dict(steps={}, rejected=0))
    rows = {step: int(observed['steps'].get(step, {}).get('rows', 0)) for step in STEPS}
    stale = {step: int(observed['steps'].get(step, {}).get('stale', 0)) for step in STEPS}
    deduplicated = {step: int(observed['steps'].get(step, {}).get('duplicates', 0))
                    for step in STEPS}
    duplicates = sum(max(0, rows[step] - 1) for step in STEPS)
    completed = all(rows[step] >= 1 for step in STEPS)
    bytes_used = logical_bytes(directory)
    result = dict(scenario='A', fault=fault, policy=policy, seed=seed, workflow=workflow,
                  terminal=outcomes[STEPS[-1]]['terminal'] if len(outcomes) == len(STEPS)
                  else outcomes[list(outcomes)[-1]]['terminal'],
                  rows=rows, stale=stale, deduplicated=deduplicated,
                  duplicates=duplicates, completed=completed,
                  safe=completed and duplicates == 0 and sum(stale.values()) == 0,
                  rejected=int(observed['rejected']), requests=calls,
                  bytes=bytes_used, elapsed_ns=elapsed)
    save(directory / 'result.json', result)
    return result


def task_b(run, policy, seed, python):
    workflow = f'B_{policy}_S{seed}'
    directory = run / 'B' / f'{policy}_s{seed}'
    directory.mkdir(parents=True)
    (directory / 'faults.json').write_text('{}', encoding='utf-8')
    (directory / 'closure').write_text('faithful', encoding='utf-8')
    capability = 'fenced' if policy == 'fenced' else 'dedup'
    process = subprocess.Popen([python, str(ROOT / 'scripts/r44_service.py'),
                                '--run-root', str(directory),
                                '--capability', capability],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    started = time.perf_counter_ns()
    try:
        base = wait_ready(directory, process)
        client = r44_client.Client(base)
        version = client.manifest().get('version', '')
        old_intent, new_intent = 'seat:12A', 'seat:14C'
        old_op, new_op = f'{workflow}:attach:12A', f'{workflow}:attach:14C'
        if policy == 'fenced':
            first = r44_client.fenced(client, workflow, old_op, 'attach', old_intent)
            second = r44_client.fenced(client, workflow, new_op, 'attach', new_intent)
        else:
            mode = 'unversioned' if policy == 'dedup_unversioned' else 'versioned'
            if mode == 'unversioned':
                old_key = new_key = key_of('unversioned', workflow, 'attach', old_intent,
                                           version)
            else:
                old_key = key_of('versioned', workflow, 'attach', old_intent, version)
                new_key = key_of('versioned', workflow, 'attach', new_intent, version)
            first = r44_client.dedup(client, workflow, old_op, 'attach', old_intent, old_key)
            second = r44_client.dedup(client, workflow, new_op, 'attach', new_intent, new_key)
        client.stop()
        calls = client.calls
    finally:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    elapsed = time.perf_counter_ns() - started
    stats = json.loads((directory / 'private' / 'stats.json').read_text(encoding='utf-8'))
    new_rows = int(stats.get(workflow, {}).get('steps', {}).get('attach', {}).get('rows', 0))
    intents = stats.get(workflow, {}).get('steps', {}).get('attach', {}).get('intents', [])
    false_complete = second['terminal'] == 'complete' and new_intent not in intents
    binding_ok = new_intent in intents and old_intent in intents
    bytes_used = logical_bytes(directory)
    result = dict(scenario='B', policy=policy, seed=seed, workflow=workflow,
                  old_terminal=first['terminal'], new_terminal=second['terminal'],
                  total_rows=new_rows, intents=intents, binding_ok=binding_ok,
                  false_complete=false_complete, requests=calls,
                  bytes=bytes_used, elapsed_ns=elapsed)
    save(directory / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    run = ROOT / 'runs' / 'R44' / args.attempt
    run.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        source, destination = ROOT / name, run / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    save(run / 'freeze.json', dict(files=hashes, faults=FAULTS, policies_a=POLICIES_A,
                                   policies_b=POLICIES_B, seeds_a=SEEDS_A, seeds_b=SEEDS_B,
                                   python=sys.executable,
                                   python_version=platform.python_version(),
                                   created_ns=time.time_ns()))
    tasks, failures = [], []
    for fault in FAULTS:
        for policy in POLICIES_A:
            for seed in SEEDS_A:
                try:
                    tasks.append(task_a(run, fault, policy, seed, sys.executable))
                except BaseException as error:
                    failures.append(dict(scenario='A', fault=fault, policy=policy, seed=seed,
                                         type=type(error).__name__, message=str(error),
                                         traceback=traceback.format_exc()))
    for policy in POLICIES_B:
        for seed in SEEDS_B:
            try:
                tasks.append(task_b(run, policy, seed, sys.executable))
            except BaseException as error:
                failures.append(dict(scenario='B', policy=policy, seed=seed,
                                     type=type(error).__name__, message=str(error),
                                     traceback=traceback.format_exc()))
    save(run / 'completion.json', dict(tasks=tasks, failures=failures))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
