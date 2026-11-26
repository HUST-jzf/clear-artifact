"""Run R27: the same CLEAR decisions, reached through a decorator."""
import argparse
import ast
import hashlib
import importlib.metadata
import json
import platform
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import anyio
import r4_holdout
import r27_guard
from run_r4 import CASES, EXPECTED, SEED_PARAMS, SOURCES

SEEDS = [1, 2, 3, 4, 5]
SOURCES_USED = ['smolagents', 'pydantic_ai', 'llamaindex']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def core_lines(path=ROOT / 'scripts/r27_guard.py', name='guarded'):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    node = next(item for item in tree.body
                if isinstance(item, ast.FunctionDef) and item.name == name)
    start, end = node.body[0].lineno, node.body[-1].end_lineno
    lines = Path(path).read_text(encoding='utf-8').splitlines()[start - 1:end]
    return sum(1 for line in lines
               if line.strip() and not line.strip().startswith('#'))


async def task(run, source, case, seed):
    host = r27_guard.GuardHost(run / f"{source}_s{seed}_{case['id']}", case['route'],
                               SOURCES[source]['adapter'], case['patch'])
    result = None
    try:
        await host.prepare()
        call = r27_guard.guarded(host, after_initial=host.apply_patch)(host.first_attempt)
        result = await call()
        result.update(case=case['id'], elapsed_ns=time.perf_counter_ns() - host.begin_ns)
        save(host.directory / 'result.json', result)
    except BaseException as error:
        save(host.directory / 'failure.json', dict(type=type(error).__name__,
                                                   message=str(error),
                                                   traceback=traceback.format_exc()))
        raise
    finally:
        await host.drain()
        await host.save()
    return dict(case=case['id'], seed=seed, terminal=result['terminal'],
                reason=result['reason'], actions=len(result['events']),
                elapsed_ns=result['elapsed_ns'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, choices=SOURCES_USED)
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    source = SOURCES[args.source]
    run_dir = ROOT / 'runs' / 'R27' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=True)
    names = ['docs/R27_middleware_integration_protocol.md', 'scripts/r27_guard.py',
             'scripts/run_r27.py', 'scripts/verify_r27.py', 'scripts/r4_holdout.py']
    hashes = {}
    for name in names:
        src, dest = ROOT / name, run_dir / 'snapshots' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        hashes[name] = sha(src)
    save(run_dir / f'freeze_{args.source}.json',
         dict(source=args.source, files=hashes, cases=[case['id'] for case in CASES],
              seeds=SEEDS, expected=EXPECTED, guard_core_lines=core_lines(),
              adapter_change_lines=1, config_items=['budget', 'after_initial'],
              business_changes=0, target_calls_before_freeze=0,
              python=sys.executable, python_version=platform.python_version(),
              created_ns=time.time_ns()))
    try:
        versions = {name: importlib.metadata.version(name)
                    for name in ['clear-assurance', source['distribution']]}
        assert versions['clear-assurance'] == '2.0.0'
        assert versions[source['distribution']] == source['version']
        results, failures = [], []
        for seed in SEEDS:
            gate, timeout, wait = SEED_PARAMS[seed]
            r4_holdout.GATE_DELAY_S = gate
            r4_holdout.INITIAL_TIMEOUT = timeout
            r4_holdout.WAIT_WINDOW = wait
            for case in CASES:
                try:
                    results.append(anyio.run(task, run_dir, args.source, case, seed))
                except BaseException as error:
                    failures.append(dict(case=case['id'], seed=seed,
                                         type=type(error).__name__, message=str(error),
                                         traceback=traceback.format_exc()))
        save(run_dir / f'completion_{args.source}.json',
             dict(source=args.source, versions=versions, prefix=sys.prefix,
                  guard_core_lines=core_lines(), adapter_change_lines=1,
                  config_items=['budget', 'after_initial'], business_changes=0,
                  tasks=results, failures=failures))
    except BaseException as error:
        save(run_dir / f'failure_{args.source}.json',
             dict(type=type(error).__name__, message=str(error),
                  traceback=traceback.format_exc()))
        raise


if __name__ == '__main__':
    main()
