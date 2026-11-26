"""R47: task-level intent change and old-effect disposal.

Three cases (`change_before_commit`, `change_after_commit`, `late_after_b`) and
four disposals (`none`, `compensate`, `transfer`, `pause`).  Runs 1-3 perform the
disposal on a clean network; runs 4-6 inject `lost_before_commit` on the
disposal request itself, which is the new failure window the disposal adds.
"""
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
import r47_client

CASES = ['change_before_commit', 'change_after_commit', 'late_after_b']
DISPOSALS = ['none', 'compensate_after_commit', 'ownership_transfer', 'pause_escalate']
RUNS = 6
LATE_DELAY = 0.9
NAMES = ['docs/R47_task_level_intent_protocol_20261029.md', 'scripts/r47_service.py',
         'scripts/r47_client.py', 'scripts/run_r47.py', 'scripts/verify_r47.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8')


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


def faults_for(workflow, case, disposal, index):
    faults = {}
    if case == 'change_before_commit':
        faults['A'] = dict(kind='lost_return')
    elif case == 'late_after_b':
        faults['A'] = dict(kind='late_commit', delay=LATE_DELAY)
    if disposal in ('compensate_after_commit', 'ownership_transfer') and index >= 4:
        faults['dispose'] = dict(kind='lost_before_commit')
    return faults


def run_task(client, workflow, case, disposal, index):
    op_a, op_b = f'{workflow}:attach:12A', f'{workflow}:attach:14C'
    intent_a, intent_b = 'seat:12A', 'seat:14C'
    first = client.write(workflow, op_a, intent_a, '12A', 1, 'A')
    old = client.active(workflow, op_a)
    escalated = False
    outcome = 'pending'
    if disposal == 'pause_escalate':
        if old:
            escalated = True
            outcome = 'escalated'
        else:
            client.write(workflow, op_b, intent_b, '14C', 1, 'B')
            outcome = 'written_after_check'
    elif disposal == 'none':
        client.write(workflow, op_b, intent_b, '14C', 1, 'B')
        outcome = 'written'
    elif disposal == 'compensate_after_commit':
        client.write(workflow, op_b, intent_b, '14C', 1, 'B')
        client.compensate(workflow, op_a, intent_a)
        outcome = 'compensated'
    else:
        client.transfer(workflow, op_a, intent_a, op_b, intent_b, '14C')
        outcome = 'transferred'
    return dict(first_ok=first['ok'], old_active=len(old), escalated=escalated,
                outcome=outcome)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--runs', type=int, default=RUNS)
    args = parser.parse_args()
    run = ROOT / 'runs' / 'R47' / args.attempt
    run.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        source = ROOT / name
        if not source.exists():
            continue
        destination = run / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    save(run / 'freeze.json', dict(files=hashes, cases=CASES, disposals=DISPOSALS,
                                   runs=args.runs, late_delay_s=LATE_DELAY,
                                   post_timeout_s=r47_client.POST_TIMEOUT,
                                   python=sys.executable,
                                   python_version=platform.python_version(),
                                   created_ns=time.time_ns()))
    faults = {}
    for case in CASES:
        for disposal in DISPOSALS:
            for index in range(1, args.runs + 1):
                workflow = f'{case}_{disposal}_R{index}'
                faults[workflow] = faults_for(workflow, case, disposal, index)
    save(run / 'faults.json', faults)
    log = (run / 'service.log').open('w', encoding='utf-8')
    process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/r47_service.py'),
                                '--run-root', str(run)],
                               cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    tasks, failures = [], []
    try:
        base = wait_ready(run, process)
        client = r47_client.Client(base)
        for case in CASES:
            for disposal in DISPOSALS:
                for index in range(1, args.runs + 1):
                    workflow = f'{case}_{disposal}_R{index}'
                    try:
                        task = run_task(client, workflow, case, disposal, index)
                        task.update(case=case, disposal=disposal, run=index,
                                    workflow=workflow)
                        tasks.append(task)
                    except BaseException as error:
                        failures.append(dict(case=case, disposal=disposal, run=index,
                                             type=type(error).__name__,
                                             message=str(error),
                                             traceback=traceback.format_exc()))
        time.sleep(LATE_DELAY + 0.3)
        client.stop()
        process.wait(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        log.close()
    stats = json.loads((run / 'private' / 'stats.json').read_text(encoding='utf-8'))
    for task in tasks:
        observed = stats.get(task['workflow'], dict(effects=[], mutations=0, epochs={}))
        active = [row for row in observed['effects']
                  if row['kind'] == 'effect' and row['state'] == 'active']
        residual = sum(1 for row in active if row['intent'] != 'seat:14C')
        new_effects = sum(1 for row in active if row['intent'] == 'seat:14C')
        duplicates = max(0, new_effects - 1)
        task.update(residual=residual, new_effects=new_effects, duplicates=duplicates,
                    task_complete=(new_effects == 1 and residual == 0),
                    writes=int(observed['mutations']),
                    visible_inconsistency=(residual > 0 or duplicates > 0),
                    effects=observed['effects'], epochs=observed.get('epochs', {}))
    save(run / 'completion.json', dict(tasks=tasks, failures=failures, cases=CASES,
                                       disposals=DISPOSALS, runs=args.runs))
    print(json.dumps(dict(tasks=len(tasks), failures=len(failures))))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
