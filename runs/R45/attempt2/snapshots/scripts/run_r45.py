"""R45: run the capability-frontier campaign.

Ten profiles (C0-C7 plus the stale-read variants C2s/C3s).  Each profile runs in
its own service process with the six capability axes fixed; every
(policy, fault, seed) is a separate workflow with its own SQLite file.

The policy set of a profile is restricted to the policies that can use the
endpoints the profile exposes, so a failing cell is never explained by "the
policy was not allowed to use a capability the service had".
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
FAULTS = ['lost_return', 'late_commit', 'lost_before_commit', 'revoke']
LATE_DELAY = 0.9
PROFILES = {
    'C0': dict(closure=0, read='unavailable', version=0, admission=0, staging=0, dedup=0),
    'C1': dict(closure=1, read='unavailable', version=0, admission=0, staging=0, dedup=0),
    'C2': dict(closure=0, read='faithful', version=0, admission=0, staging=0, dedup=0),
    'C2s': dict(closure=0, read='stale', version=0, admission=0, staging=0, dedup=0),
    'C3': dict(closure=1, read='faithful', version=0, admission=0, staging=0, dedup=0),
    'C3s': dict(closure=1, read='stale', version=0, admission=0, staging=0, dedup=0),
    'C4': dict(closure=1, read='faithful', version=1, admission=1, staging=0, dedup=0),
    'C5': dict(closure=0, read='unavailable', version=0, admission=0, staging=1, dedup=0),
    'C6': dict(closure=1, read='faithful', version=1, admission=1, staging=1, dedup=0),
    'C7': dict(closure=0, read='unavailable', version=0, admission=0, staging=0, dedup=1),
}
PROFILE_POLICIES = {
    'C0': ['clear_pause', 'timeout_retry'],
    'C1': ['clear_closure', 'timeout_retry'],
    'C2': ['verify_retry', 'timeout_retry'],
    'C2s': ['verify_retry', 'timeout_retry'],
    'C3': ['clear_evidence', 'verify_retry'],
    'C3s': ['clear_evidence', 'verify_retry'],
    'C4': ['clear_evidence', 'verify_retry', 'timeout_retry'],
    'C5': ['clear_fenced', 'timeout_retry'],
    'C6': ['clear_evidence', 'clear_fenced', 'timeout_retry'],
    'C7': ['dedup_versioned', 'timeout_retry'],
}
NAMES = ['docs/R45_capability_frontier_protocol_20261029.md', 'scripts/r45_service.py',
         'scripts/r45_client.py', 'scripts/run_r45.py', 'scripts/verify_r45.py']


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


def workflow_id(profile, fault, policy, seed):
    return f'{profile}_{fault}_{policy}_S{seed}'


def run_workflow(client, workflow, policy, axes):
    outcomes = {}
    for step in STEPS:
        outcome = r45_client.POLICIES[policy](client, workflow, step, axes)
        outcomes[step] = outcome
        if outcome['terminal'] != 'complete':
            break
    return outcomes


def run_profile(run, profile, seeds, python):
    directory = run / profile
    directory.mkdir(parents=True)
    policies = PROFILE_POLICIES[profile]
    faults = {workflow_id(profile, fault, policy, seed):
              {'attach': dict(kind=fault, delay=LATE_DELAY)}
              for fault in FAULTS for policy in policies for seed in seeds}
    save(directory / 'faults.json', faults)
    save(directory / 'profile.json', dict(profile=profile, axes=PROFILES[profile],
                                          policies=policies, faults=FAULTS, seeds=seeds))
    log = (directory / 'service.log').open('w', encoding='utf-8')
    process = subprocess.Popen([python, str(ROOT / 'scripts/r45_service.py'),
                                '--run-root', str(directory), '--profile', profile],
                               cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    tasks = []
    try:
        base = wait_ready(directory, process)
        client = r45_client.Client(base)
        axes = PROFILES[profile]
        for fault in FAULTS:
            for policy in policies:
                for seed in seeds:
                    workflow = workflow_id(profile, fault, policy, seed)
                    before = client.calls
                    started = time.perf_counter_ns()
                    outcomes = run_workflow(client, workflow, policy, axes)
                    elapsed = time.perf_counter_ns() - started
                    last = outcomes[list(outcomes)[-1]]
                    tasks.append(dict(profile=profile, policy=policy, fault=fault,
                                      seed=seed, workflow=workflow,
                                      terminal=last['terminal'], reason=last['reason'],
                                      committed=bool(last.get('committed')),
                                      steps_run=len(outcomes),
                                      requests=client.calls - before,
                                      elapsed_ns=elapsed))
        time.sleep(LATE_DELAY + 0.3)
        client.stop()
        process.wait(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        log.close()
    stats = json.loads((directory / 'private' / 'stats.json').read_text(encoding='utf-8'))
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
    parser.add_argument('--seeds', default='0-19')
    parser.add_argument('--profiles', default=','.join(PROFILES))
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    wanted = [item for item in args.profiles.split(',') if item]
    run = ROOT / 'runs' / 'R45' / args.attempt
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
        files=hashes, profiles={name: PROFILES[name] for name in wanted},
        profile_policies={name: PROFILE_POLICIES[name] for name in wanted},
        faults=FAULTS, seeds=seeds, steps=STEPS,
        post_timeout_s=r45_client.POST_TIMEOUT,
        get_timeout_s=r45_client.GET_TIMEOUT,
        retry_budget=r45_client.RETRY_BUDGET, late_delay_s=LATE_DELAY,
        python=sys.executable, python_version=platform.python_version(),
        created_ns=time.time_ns()))
    tasks, failures = [], []
    for profile in wanted:
        try:
            tasks.extend(run_profile(run, profile, seeds, sys.executable))
        except BaseException as error:
            failures.append(dict(profile=profile, type=type(error).__name__,
                                 message=str(error), traceback=traceback.format_exc()))
    save(run / 'completion.json', dict(profiles=wanted, seeds=seeds, faults=FAULTS,
                                       tasks=tasks, failures=failures))
    print(json.dumps(dict(tasks=len(tasks), failures=len(failures))))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
