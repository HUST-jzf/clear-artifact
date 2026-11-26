"""Run R34: two concurrent recoveries of one binding under three mechanisms."""
import argparse
import hashlib
import json
import platform
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import r34_client

STEPS = r34_client.STEPS
FAULTS = ['lost_return', 'lost_before_commit']
MECHANISMS = ['none', 'lease', 'unique']
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


def task(run, fault, mechanism, seed, python):
    workflow = f'{fault}_{mechanism}_S{seed}'
    directory = run / f'{fault}_{mechanism}_s{seed}'
    directory.mkdir()
    (directory / 'faults.json').write_text(
        json.dumps({workflow: {'attach': {'kind': fault}}}), encoding='utf-8')
    process = subprocess.Popen([python, str(ROOT / 'scripts/r34_service.py'),
                                '--run-root', str(directory)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    started = time.perf_counter_ns()
    try:
        base = wait_ready(directory)
        first, second = r34_client.Client(base), r34_client.Client(base)
        epoch = int(first.permit(workflow).get('epoch', 1))
        for step in ['create', 'reserve']:
            first.append(workflow, step, 1, epoch)
        first.append(workflow, 'attach', 1, epoch)
        barrier = threading.Barrier(2)
        outcomes = {}

        def recover(client, owner):
            outcomes[owner] = r34_client.recover(client, workflow, 'attach', mechanism,
                                                 owner, barrier)

        workers = [threading.Thread(target=recover, args=(first, 'A')),
                   threading.Thread(target=recover, args=(second, 'B'))]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        epoch = int(first.permit(workflow).get('epoch', 1))
        for step in ['commit', 'notify']:
            first.append(workflow, step, 1, epoch)
        steps = first.state(workflow)
        first.stop()
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
    writes = sum(outcomes[owner]['writes'] for owner in outcomes)
    result = dict(fault=fault, mechanism=mechanism, seed=seed, workflow=workflow,
                  controllers=outcomes, rows=rows, stale=stale,
                  duplicates=duplicates, completed=completed,
                  safe=completed and duplicates == 0 and sum(stale.values()) == 0,
                  writes=writes, elapsed_ns=time.perf_counter_ns() - started,
                  observed_steps=steps)
    save(directory / 'result.json', result)
    return dict(fault=fault, mechanism=mechanism, seed=seed, rows=rows['attach'],
                duplicates=duplicates, safe=result['safe'], writes=writes,
                terminals={owner: outcomes[owner]['terminal'] for owner in outcomes})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    run = ROOT / 'runs' / 'R34' / args.attempt
    run.mkdir(parents=True, exist_ok=False)
    names = ['docs/R34_dual_controller_protocol.md', 'scripts/r34_service.py',
             'scripts/r34_client.py', 'scripts/run_r34.py', 'scripts/verify_r34.py']
    hashes = {}
    for name in names:
        source, destination = ROOT / name, run / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    save(run / 'freeze.json', dict(files=hashes, faults=FAULTS, mechanisms=MECHANISMS,
                                   seeds=SEEDS, target_calls_before_freeze=0,
                                   python=sys.executable,
                                   python_version=platform.python_version(),
                                   created_ns=time.time_ns()))
    tasks, failures = [], []
    for fault in FAULTS:
        for mechanism in MECHANISMS:
            for seed in SEEDS:
                try:
                    tasks.append(task(run, fault, mechanism, seed, sys.executable))
                except BaseException as error:
                    failures.append(dict(fault=fault, mechanism=mechanism, seed=seed,
                                         type=type(error).__name__, message=str(error),
                                         traceback=traceback.format_exc()))
    save(run / 'completion.json', dict(tasks=tasks, failures=failures))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
