"""Run R39: a real LLM agent under three coordination modes."""
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
import r38_client
import r39_agent

STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
TOOL_STEPS = r39_agent.STEPS
GUARDS = ['blind', 'evidence', 'clear']
FAULTS = ['none', 'lost_return', 'late_effect', 'late_effect_slow',
          'lost_before_commit']
RUNS = {'none': 4, 'lost_return': 6, 'late_effect': 6, 'late_effect_slow': 6,
        'lost_before_commit': 6}
FAULT_SPEC = {'lost_return': ('lost_return', 1.0), 'late_effect': ('late_effect', 1.0),
              'late_effect_slow': ('late_effect', 5.0),
              'lost_before_commit': ('lost_before_commit', 1.0)}
DRAIN_SECONDS = 6.0


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


def retries_after_timeout(calls):
    seen_timeout, retries = set(), 0
    for call in calls:
        tool = call['tool']
        if tool in seen_timeout:
            retries += 1
        if call['result'].get('status') == 'timeout':
            seen_timeout.add(tool)
    return retries


def task(run, guard, fault, index, python, key):
    workflow = f'{guard}_{fault}_R{index}'
    directory = run / f'{guard}_{fault}_r{index}'
    directory.mkdir()
    faults = {}
    if fault != 'none':
        kind, delay = FAULT_SPEC[fault]
        faults = {workflow: {'attach': {'kind': kind, 'delay': delay}}}
    (directory / 'faults.json').write_text(json.dumps(faults), encoding='utf-8')
    (directory / 'closure').write_text('absent', encoding='utf-8')
    process = subprocess.Popen([python, str(ROOT / 'scripts/r38_service.py'),
                                '--run-root', str(directory)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    started = time.perf_counter_ns()
    try:
        base = wait_ready(directory)
        client = r38_client.Client(base)
        agent = r39_agent.run_agent(client, workflow, guard)
        time.sleep(DRAIN_SECONDS)
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
    duplicates = sum(max(0, rows[step] - 1) for step in STEPS)
    completed = all(rows[step] >= 1 for step in STEPS)
    result = dict(guard=guard, fault=fault, run=index, workflow=workflow,
                  rows=rows, stale=stale, duplicates=duplicates,
                  completed=completed, finished=agent['finished'],
                  tool_calls=len(agent['calls']),
                  retries_after_timeout=retries_after_timeout(agent['calls']),
                  ledger=agent['ledger'], model=agent['model'],
                  temperature=agent['temperature'], drain_seconds=DRAIN_SECONDS,
                  key_leak=False, elapsed_ns=time.perf_counter_ns() - started)
    save(directory / 'transcript.json', dict(messages=agent['messages'],
                                             calls=agent['calls']))
    save(directory / 'result.json', result)
    leak = key_leaked(directory, key)
    if leak:
        raise RuntimeError('api key leaked into ' + leak)
    return dict(guard=guard, fault=fault, run=index, rows=rows['attach'],
                duplicates=duplicates, stale=sum(stale.values()),
                completed=completed, tool_calls=result['tool_calls'],
                retries_after_timeout=result['retries_after_timeout'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    key = os.environ.get('DEEPSEEK_API_KEY')
    if not key:
        raise SystemExit('DEEPSEEK_API_KEY is required')
    run = ROOT / 'runs' / 'R39' / args.attempt
    run.mkdir(parents=True, exist_ok=False)
    names = ['docs/R39_real_llm_protocol.md', 'scripts/r39_agent.py',
             'scripts/run_r39.py', 'scripts/verify_r39.py', 'scripts/r38_service.py',
             'scripts/r38_client.py']
    hashes = {}
    for name in names:
        source, destination = ROOT / name, run / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    save(run / 'freeze.json', dict(files=hashes, guards=GUARDS, faults=FAULTS,
                                   runs=RUNS, model=r39_agent.MODEL,
                                   temperature=r39_agent.TEMPERATURE,
                                   max_tokens=r39_agent.MAX_TOKENS,
                                   max_turns=r39_agent.MAX_TURNS,
                                   drain_seconds=DRAIN_SECONDS,
                                   target_calls_before_freeze=0,
                                   python=sys.executable,
                                   python_version=platform.python_version(),
                                   created_ns=time.time_ns()))
    tasks, failures = [], []
    for guard in GUARDS:
        for fault in FAULTS:
            for index in range(1, RUNS[fault] + 1):
                try:
                    tasks.append(task(run, guard, fault, index, sys.executable, key))
                except BaseException as error:
                    failures.append(dict(guard=guard, fault=fault, run=index,
                                         type=type(error).__name__, message=str(error),
                                         traceback=traceback.format_exc()))
    save(run / 'completion.json', dict(tasks=tasks, failures=failures))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
