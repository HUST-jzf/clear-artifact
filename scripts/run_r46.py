"""R46: identity regime x call variant x policy.

Three regimes (`fixed`, `fresh`, `none`), three call variants (`exact`,
`paraphrase`, `same_args_new_intent`) and the policies that can be built in each
regime.  Scenario A recovers a faulted `attach`; scenario B asks for a different
intent with identical arguments.
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
import r46_client

ARGS = {'seat': '12A'}
INTENT = 'seat:12A'
PARAPHRASE = 'assign seat 12A'
NEW_INTENT = 'hold:12A'
FAULTS = ['lost_return', 'late_commit']
VARIANTS = ['exact', 'paraphrase']
LATE_DELAY = 0.9
REGIMES = {
    'fixed': dict(dedup='keyed',
                  policies=['dedup_versioned', 'semantic_dedup', 'verify_retry',
                            'clear_fenced', 'clear_evidence']),
    'fresh': dict(dedup='keyed',
                  policies=['dedup_fresh', 'semantic_dedup', 'verify_retry',
                            'clear_fenced', 'clear_evidence']),
    'none': dict(dedup='content',
                 policies=['semantic_dedup', 'verify_retry', 'clear_fenced',
                           'clear_evidence']),
}
NAMES = ['docs/R46_identity_semantics_protocol_20261029.md', 'scripts/r46_service.py',
         'scripts/r46_client.py', 'scripts/run_r46.py', 'scripts/verify_r46.py']


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


def run_id(regime, policy, cell, seed):
    return f'{regime}_{policy}_{cell}_S{seed}'


def scenario_a(client, policy, workflow, fault, variant, second_intent):
    op = f'{workflow}:attach'
    policy_map = r46_client.POLICIES[policy]
    first = policy_map['initial'](client, workflow, op, INTENT, ARGS, 1)
    second = policy_map['recover'](client, workflow, op, second_intent, ARGS, 2)
    return dict(fault=fault, variant=variant, op=op, first=first, second=second,
                intents=[INTENT, second_intent])


def scenario_b(client, policy, workflow):
    """Same op and same arguments, different intent: only an intent-aware
    identity can keep the two effects apart."""
    op = f'{workflow}:attach'
    policy_map = r46_client.POLICIES[policy]
    first = policy_map['initial'](client, workflow, op, INTENT, ARGS, 1)
    second = policy_map['initial'](client, workflow, op, NEW_INTENT, ARGS, 1)
    return dict(fault='none', variant='same_args_new_intent', op=op, first=first,
                second=second, intents=[INTENT, NEW_INTENT])


def run_combo(run, regime, policy, seeds, python):
    directory = run / f'{regime}_{policy}'
    directory.mkdir(parents=True)
    cells = [(f'A_{fault}_{variant}', fault, variant)
             for fault in FAULTS for variant in VARIANTS] + [('B', 'none', 'B')]
    faults = {}
    for fault in FAULTS:
        for variant in VARIANTS:
            for seed in seeds:
                faults[run_id(regime, policy, f'A_{fault}_{variant}', seed)] = {
                    'attach': dict(kind=fault, delay=LATE_DELAY)}
    save(directory / 'faults.json', faults)
    save(directory / 'plan.json', dict(regime=regime, policy=policy,
                                       dedup=REGIMES[regime]['dedup'],
                                       cells=[cell[0] for cell in cells], seeds=seeds))
    log = (directory / 'service.log').open('w', encoding='utf-8')
    process = subprocess.Popen([python, str(ROOT / 'scripts/r46_service.py'),
                                '--run-root', str(directory),
                                '--dedup', REGIMES[regime]['dedup']],
                               cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    tasks = []
    try:
        base = wait_ready(directory, process)
        client = r46_client.Client(base)
        for label, fault, variant in cells:
            for seed in seeds:
                workflow = run_id(regime, policy, label, seed)
                before = client.calls
                started = time.perf_counter_ns()
                if label == 'B':
                    outcome = scenario_b(client, policy, workflow)
                else:
                    second_intent = PARAPHRASE if variant == 'paraphrase' else INTENT
                    outcome = scenario_a(client, policy, workflow, fault, variant,
                                         second_intent)
                tasks.append(dict(regime=regime, policy=policy, cell=label,
                                  fault=fault, variant=variant, seed=seed,
                                  workflow=workflow, op=outcome['op'] if 'op' in outcome
                                  else None,
                                  first=outcome['first'], second=outcome['second'],
                                  requests=client.calls - before,
                                  elapsed_ns=time.perf_counter_ns() - started))
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
        observed = stats.get(task['workflow'], dict(ops={}))
        ops = observed.get('ops', {})
        effects = sum(entry['effects'] for entry in ops.values())
        intents = [intent for entry in ops.values() for intent in entry['intents']]
        if task['cell'] == 'B':
            present = sorted(set(intents))
            second_intent = 'hold:12A' in present
            false_merge = (task['second']['terminal'] == 'complete' and not second_intent)
            task.update(effects=effects, intents=intents, false_merge=false_merge,
                        duplicate=False, false_split=False,
                        correct=(effects == 2 and len(present) == 2),
                        safe_complete=(task['second']['terminal'] == 'complete'
                                       and not false_merge),
                        paused=task['second']['terminal'] == 'pause')
        else:
            duplicate = effects > 1 and len(set(intents)) == 1
            false_split = effects > 1 and len(set(intents)) > 1
            task.update(effects=effects, intents=intents, duplicate=duplicate,
                        false_split=false_split, false_merge=False,
                        correct=effects == 1,
                        safe_complete=(task['second']['terminal'] == 'complete'
                                       and effects == 1),
                        paused=task['second']['terminal'] == 'pause')
    save(directory / 'outcomes.json', tasks)
    return tasks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--seeds', default='0-9')
    parser.add_argument('--regimes', default=','.join(REGIMES))
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    wanted = [item for item in args.regimes.split(',') if item]
    run = ROOT / 'runs' / 'R46' / args.attempt
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
    save(run / 'freeze.json', dict(files=hashes, regimes={name: REGIMES[name]
                                                          for name in wanted},
                                   faults=FAULTS, variants=VARIANTS, seeds=seeds,
                                   args=ARGS, intent=INTENT, paraphrase=PARAPHRASE,
                                   new_intent=NEW_INTENT,
                                   post_timeout_s=r46_client.POST_TIMEOUT,
                                   late_delay_s=LATE_DELAY,
                                   python=sys.executable,
                                   python_version=platform.python_version(),
                                   created_ns=time.time_ns()))
    tasks, failures = [], []
    for regime in wanted:
        for policy in REGIMES[regime]['policies']:
            try:
                tasks.extend(run_combo(run, regime, policy, seeds, sys.executable))
            except BaseException as error:
                failures.append(dict(regime=regime, policy=policy,
                                     type=type(error).__name__, message=str(error),
                                     traceback=traceback.format_exc()))
    save(run / 'completion.json', dict(regimes=wanted, seeds=seeds, tasks=tasks,
                                       failures=failures))
    print(json.dumps(dict(tasks=len(tasks), failures=len(failures))))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
