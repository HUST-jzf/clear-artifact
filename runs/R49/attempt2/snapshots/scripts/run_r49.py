"""R49: run the retrofit-cost campaign.

Four retrofit levels (L0-L3, mapped to the R45 profiles C0, C3, C4 and C6) are
requested under three ownership regimes.  `read_only` collapses L2/L3 to L1 and
`unmodifiable` collapses every level to L0; the collapse is the treatment.

One service process per effective profile.  Every (ownership, level, fault,
seed) is a separate workflow with its own SQLite file, named after the
requested level so that collapsed cells stay distinguishable.
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
import r45_client

STEPS = r45_client.STEPS
FAULTS = ['lost_return', 'late_commit']
LATE_DELAY = 0.9
LEVEL_PROFILE = {'L0': 'C0', 'L1': 'C3', 'L2': 'C4', 'L3': 'C6'}
OWNERSHIP = {
    'self': {'L0': 'L0', 'L1': 'L1', 'L2': 'L2', 'L3': 'L3'},
    'read_only': {'L0': 'L0', 'L1': 'L1', 'L2': 'L1', 'L3': 'L1'},
    'unmodifiable': {'L0': 'L0', 'L1': 'L0', 'L2': 'L0', 'L3': 'L0'},
}
PROFILE_POLICY = {'C0': 'clear_pause', 'C3': 'clear_evidence',
                  'C4': 'clear_evidence', 'C6': 'clear_fenced'}
PROFILES = {
    'C0': dict(closure=0, read='unavailable', version=0, admission=0, staging=0, dedup=0),
    'C3': dict(closure=1, read='faithful', version=0, admission=0, staging=0, dedup=0),
    'C4': dict(closure=1, read='faithful', version=1, admission=1, staging=0, dedup=0),
    'C6': dict(closure=1, read='faithful', version=1, admission=1, staging=1, dedup=0),
}
NAMES = ['docs/R49_retrofit_cost_protocol_20261029.md', 'scripts/r45_service.py',
         'scripts/r45_client.py', 'scripts/run_r49.py', 'scripts/verify_r49.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8')


def logical_bytes(path):
    db = sqlite3.connect(path)
    try:
        return int(db.execute('pragma page_count').fetchone()[0]) * \
            int(db.execute('pragma page_size').fetchone()[0])
    finally:
        db.close()


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


def workflow_id(ownership, level, fault, seed):
    return f'{ownership}_{level}_{fault}_S{seed}'


class Client(r45_client.Client):
    """R45 client that records every non-successful exchange.

    A transport failure is not a service behaviour; recording it separately
    keeps such a workflow out of the capability argument.
    """

    def __init__(self, base_url):
        super().__init__(base_url)
        self.errors = []

    def request(self, method, path, body=None, timeout=r45_client.GET_TIMEOUT):
        response = super().request(method, path, body, timeout)
        status = response.get('status')
        if status is None or status >= 500:
            self.errors.append(dict(method=method, path=path, status=status,
                                    error=response.get('error')))
        return response


def effective_profile(ownership, level):
    return LEVEL_PROFILE[OWNERSHIP[ownership][level]]


def plan(seeds):
    cells = []
    for ownership in OWNERSHIP:
        for level in LEVEL_PROFILE:
            for fault in FAULTS:
                for seed in seeds:
                    cells.append(dict(ownership=ownership, level=level, fault=fault,
                                      seed=seed, profile=effective_profile(ownership, level),
                                      policy=PROFILE_POLICY[effective_profile(ownership, level)],
                                      workflow=workflow_id(ownership, level, fault, seed)))
    return cells


def run_workflow(client, workflow, policy, axes):
    outcomes, errors = {}, []
    for step in STEPS:
        before = len(client.errors)
        outcome = r45_client.POLICIES[policy](client, workflow, step, axes)
        outcomes[step] = outcome
        errors.extend(dict(error, step=step) for error in client.errors[before:])
        if outcome['terminal'] != 'complete':
            break
    return outcomes, errors


def run_profile(run, profile, cells, python):
    directory = run / profile
    directory.mkdir(parents=True)
    faults = {cell['workflow']: {'attach': dict(kind=cell['fault'], delay=LATE_DELAY)}
              for cell in cells}
    save(directory / 'faults.json', faults)
    save(directory / 'profile.json', dict(profile=profile, axes=PROFILES[profile],
                                          policy=PROFILE_POLICY[profile],
                                          workflows=sorted(faults)))
    log = (directory / 'service.log').open('w', encoding='utf-8')
    process = subprocess.Popen([python, str(ROOT / 'scripts/r45_service.py'),
                                '--run-root', str(directory), '--profile', profile],
                               cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    tasks = []
    try:
        base = wait_ready(directory, process)
        client = Client(base)
        axes = PROFILES[profile]
        for cell in cells:
            before = client.calls
            started = time.perf_counter_ns()
            outcomes, errors = run_workflow(client, cell['workflow'], cell['policy'], axes)
            elapsed = time.perf_counter_ns() - started
            last = outcomes[list(outcomes)[-1]]
            tasks.append(dict(cell, terminal=last['terminal'], reason=last['reason'],
                              committed=bool(last.get('committed')),
                              steps_run=len(outcomes), requests=client.calls - before,
                              transport_errors=errors, elapsed_ns=elapsed))
        time.sleep(LATE_DELAY + 0.3)
        client.stop()
        deadline = time.time() + 10
        while time.time() < deadline and not (directory / 'private' / 'stats.json').exists():
            time.sleep(0.05)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        log.close()
    stats_path = directory / 'private' / 'stats.json'
    if not stats_path.exists():
        raise RuntimeError(f'service did not write stats for profile {profile}')
    stats = json.loads(stats_path.read_text(encoding='utf-8'))
    for task in tasks:
        observed = stats.get(task['workflow'], dict(steps={}, rejected=0))
        rows = {step: int(observed['steps'].get(step, {}).get('committed', 0))
                for step in STEPS}
        stale = sum(int(observed['steps'].get(step, {}).get('stale', 0)) for step in STEPS)
        provisional = sum(int(observed['steps'].get(step, {}).get('provisional', 0))
                          for step in STEPS)
        duplicates = sum(max(0, rows[step] - 1) for step in STEPS)
        completed = all(rows[step] >= 1 for step in STEPS)
        false_complete = (task['terminal'] == 'complete'
                          and (not completed or duplicates > 0 or stale > 0))
        task.update(rows=rows, stale=stale, provisional=provisional,
                    duplicates=duplicates, completed=completed,
                    safe=duplicates == 0 and stale == 0 and not false_complete,
                    false_complete=false_complete,
                    rejected=int(observed.get('rejected', 0)),
                    bytes=logical_bytes(directory / 'private'
                                        / (task['workflow'] + '.sqlite')))
    save(directory / 'outcomes.json', tasks)
    return tasks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--seeds', default='0-9')
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    run = ROOT / 'runs' / 'R49' / args.attempt
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
    save(run / 'freeze.json', dict(
        files=hashes, levels=LEVEL_PROFILE, ownership=OWNERSHIP,
        profile_policy=PROFILE_POLICY, profiles=PROFILES, faults=FAULTS, seeds=seeds,
        steps=STEPS, post_timeout_s=r45_client.POST_TIMEOUT,
        get_timeout_s=r45_client.GET_TIMEOUT, retry_budget=r45_client.RETRY_BUDGET,
        late_delay_s=LATE_DELAY, python=sys.executable,
        python_version=platform.python_version(), created_ns=time.time_ns()))
    cells = plan(seeds)
    tasks, failures = [], []
    for profile in sorted(PROFILES):
        subset = [cell for cell in cells if cell['profile'] == profile]
        try:
            tasks.extend(run_profile(run, profile, subset, sys.executable))
        except BaseException as error:
            failures.append(dict(profile=profile, type=type(error).__name__,
                                 message=str(error), traceback=traceback.format_exc()))
    save(run / 'completion.json', dict(levels=LEVEL_PROFILE, ownership=OWNERSHIP,
                                       seeds=seeds, faults=FAULTS, cells=len(cells),
                                       tasks=tasks, failures=failures))
    print(json.dumps(dict(tasks=len(tasks), failures=len(failures))))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
