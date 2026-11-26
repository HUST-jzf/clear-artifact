"""Run R40: real-LLM intent change, and pause-then-repair after a service upgrade."""
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import r40_agent
import r40_client

STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
GUARDS = ['blind', 'evidence', 'clear']
SCENARIOS = ['intent_change', 'no_fence_repair']
RUNS = 6
DRAIN_SECONDS = 6.0
FAULT_SPEC = {'intent_change': ('lost_return', 1.0), 'no_fence_repair': None}


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


def key_leaked(directory, key):
    for path in directory.rglob('*'):
        if path.is_file():
            try:
                if key.encode() in path.read_bytes():
                    return str(path)
            except OSError:
                continue
    return None


def start_service(directory, python):
    ready = directory / 'ready.json'
    if ready.exists():
        ready.unlink()
    process = subprocess.Popen([python, str(ROOT / 'scripts/r40_service.py'),
                                '--run-root', str(directory)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = wait_ready(directory)
    return process, r40_client.Client(base)


def stop_service(process, client):
    client.stop()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def committed_steps(stats, workflow):
    observed = stats.get(workflow, dict(steps={}, ops=[], rejected=0))
    return {step: int(observed['steps'].get(step, {}).get('committed', 0)) for step in STEPS}


def metrics(stats, workflow, guard):
    observed = stats.get(workflow, dict(steps={}, ops=[], rejected=0))
    ops = observed.get('ops', [])
    rows = {step: int(observed['steps'].get(step, {}).get('rows', 0)) for step in STEPS}
    committed = committed_steps(stats, workflow)
    duplicates = sum(max(0, int(entry['rows']) - 1) for entry in ops)
    mixed = sum(1 for entry in ops if len(entry.get('intents') or []) > 1)
    intents = sorted({intent for entry in ops for intent in entry.get('intents') or []})
    return dict(rows=rows, committed=committed, duplicates=duplicates,
                mixed_binding=mixed, intents=intents,
                rejected=int(observed.get('rejected', 0)))


def task(run, scenario, guard, index, python, key):
    workflow = f'{scenario}_{guard}_R{index}'
    directory = run / f'{scenario}_{guard}_r{index}'
    directory.mkdir()
    spec = FAULT_SPEC[scenario]
    faults = {workflow: {'attach': {'kind': spec[0], 'delay': spec[1]}}} if spec else {}
    (directory / 'faults.json').write_text(json.dumps(faults), encoding='utf-8')
    (directory / 'closure').write_text('absent', encoding='utf-8')
    (directory / 'fence').write_text(
        'absent' if scenario == 'no_fence_repair' else 'present', encoding='utf-8')
    started = time.perf_counter_ns()
    process, client = start_service(directory, python)
    first = r40_agent.run_agent(client, workflow, guard, scenario)
    time.sleep(DRAIN_SECONDS)
    stop_service(process, client)
    phase1 = json.loads((directory / 'private' / 'stats.json').read_text(encoding='utf-8'))
    save(directory / 'phase1_stats.json', phase1)
    save(directory / 'transcript1.json', dict(messages=first['messages'],
                                              calls=first['calls']))
    first_metrics = metrics(phase1, workflow, guard)
    first_done = all(count >= 1 for count in first_metrics['committed'].values())

    repaired = False
    second = None
    if scenario == 'no_fence_repair' and not first_done:
        (directory / 'faults.json').write_text('{}', encoding='utf-8')
        (directory / 'fence').write_text('present', encoding='utf-8')
        process, client = start_service(directory, python)
        second = r40_agent.run_agent(client, workflow, guard, scenario,
                                     opening=r40_agent.RESUME)
        time.sleep(DRAIN_SECONDS)
        stop_service(process, client)
        save(directory / 'transcript2.json', dict(messages=second['messages'],
                                                  calls=second['calls']))
        repaired = True
        final = json.loads((directory / 'private' / 'stats.json').read_text(encoding='utf-8'))
    else:
        final = phase1
    after = metrics(final, workflow, guard)
    completed_after = all(count >= 1 for count in after['committed'].values())
    paused_steps = sum(1 for value in first['ledger'].values() if value == 'paused')
    paused_list = [r40_agent.STEP_IDS[key.split(':')[0]]
                   for key, value in first['ledger'].items() if value == 'paused']
    followed = any(str(seat).strip() not in ('', r40_agent.DEFAULT_SEAT)
                   for seat in first['attach_seats'])
    attach_intents = [intent for intent in after['intents']
                      if intent.startswith('ticket:attach:')]
    stale = False
    residual = 0
    if scenario == 'intent_change' and followed:
        seat = first['last_attach_seat']
        stale = not any(intent.endswith(':' + str(seat)) for intent in attach_intents)
        residual = sum(1 for intent in attach_intents
                       if not intent.endswith(':' + str(seat)))
    result = dict(scenario=scenario, guard=guard, run=index, workflow=workflow,
                  rows=after['rows'], duplicates=after['duplicates'],
                  mixed_binding=after['mixed_binding'], stale_completion=stale,
                  residual_old_intent=residual, intents=after['intents'],
                  rejected=after['rejected'],
                  phase1_completed=first_done, completed=completed_after,
                  repaired=repaired,
                  recovered=bool(repaired and paused_list
                                 and all(after['committed'][step] >= 1
                                         for step in paused_list)),
                  paused_steps=paused_steps, paused_list=paused_list, finished_first=first['finished'],
                  finished_second=bool(second and second['finished']),
                  injected=first['injected'], followed=followed,
                  nudges_first=first['nudges'],
                  nudges_second=second['nudges'] if second else 0,
                  last_attach_seat=first['last_attach_seat'],
                  tool_calls=len(first['calls']) + (len(second['calls']) if second else 0),
                  model=first['model'], temperature=first['temperature'],
                  drain_seconds=DRAIN_SECONDS, key_leak=False,
                  elapsed_ns=time.perf_counter_ns() - started)
    save(directory / 'result.json', result)
    leak = key_leaked(directory, key)
    if leak:
        raise RuntimeError('api key leaked into ' + leak)
    return dict(scenario=scenario, guard=guard, run=index, duplicates=result['duplicates'],
                mixed_binding=result['mixed_binding'], stale=result['stale_completion'],
                phase1_completed=first_done, completed=completed_after,
                recovered=result['recovered'], followed=followed,
                paused_steps=paused_steps)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    key = os.environ.get('DEEPSEEK_API_KEY')
    if not key:
        raise SystemExit('DEEPSEEK_API_KEY is required')
    run = ROOT / 'runs' / 'R40' / args.attempt
    run.mkdir(parents=True, exist_ok=False)
    names = ['docs/R40_intent_change_pause_repair_protocol.md', 'scripts/r40_agent.py',
             'scripts/r40_client.py', 'scripts/r40_service.py', 'scripts/run_r40.py',
             'scripts/verify_r40.py']
    hashes = {}
    for name in names:
        source, destination = ROOT / name, run / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    save(run / 'freeze.json', dict(files=hashes, scenarios=SCENARIOS, guards=GUARDS,
                                   runs=RUNS, model=r40_agent.MODEL,
                                   temperature=r40_agent.TEMPERATURE,
                                   max_tokens=r40_agent.MAX_TOKENS,
                                   max_turns=r40_agent.MAX_TURNS,
                                   drain_seconds=DRAIN_SECONDS,
                                   faults=FAULT_SPEC,
                                   python=sys.executable,
                                   python_version=platform.python_version(),
                                   created_ns=time.time_ns()))
    tasks, failures = [], []
    for scenario in SCENARIOS:
        for guard in GUARDS:
            for index in range(1, RUNS + 1):
                try:
                    tasks.append(task(run, scenario, guard, index, sys.executable, key))
                except BaseException as error:
                    failures.append(dict(scenario=scenario, guard=guard, run=index,
                                         type=type(error).__name__, message=str(error),
                                         traceback=traceback.format_exc()))
    save(run / 'completion.json', dict(tasks=tasks, failures=failures))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
