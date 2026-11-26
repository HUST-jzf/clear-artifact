"""Run R3 LangGraph checkpoint/resume baseline on 12 capability cells × 10 seeds."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from r3_langgraph import run

JITTER = {
    0: (0.080, 0.060), 1: (0.072, 0.052), 2: (0.076, 0.054), 3: (0.084, 0.056),
    4: (0.068, 0.050), 5: (0.074, 0.053), 6: (0.078, 0.055), 7: (0.082, 0.057),
    8: (0.086, 0.058), 9: (0.090, 0.059),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def cases():
    out = []
    for idem in [0, 1]:
        for change in ['none', 'revoke']:
            for fault in ['fail', 'lost', 'late']:
                route = dict(revision=1, mode='inline',
                             outcome='fail' if fault == 'fail' else 'commit',
                             delayed=fault == 'late', abandon_on_cancel=False,
                             delegated=False, closed_registration=True, allowed=True,
                             store='effects', idempotency=bool(idem), query_complete=True)
                out.append(dict(id=f'I{idem}Q1C1G{change}F{fault}', route=route,
                                change=change, fault=fault))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    run_dir = ROOT / 'runs/R3_langgraph' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    names = ['scripts/run_r3_langgraph.py', 'scripts/r3_langgraph.py',
             'docs/R3_LangGraph_baseline_protocol.md']
    hashes = {}
    for name in names:
        source, dest = ROOT / name, run_dir / 'snapshots' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    config = cases()
    save(run_dir / 'freeze.json', dict(files=hashes, cases=config, seeds=list(JITTER),
         jitter={str(k): dict(gate=v[0], initial_timeout=v[1]) for k, v in JITTER.items()},
         target_calls_before_freeze=0, python=sys.executable,
         python_version=platform.python_version(), created_ns=time.time_ns()))
    try:
        import langgraph
        import langgraph.checkpoint.sqlite
        import langchain_core
        versions = {name: importlib.metadata.version(name)
                    for name in ['langgraph', 'langgraph-checkpoint-sqlite', 'langchain-core']}
        assert versions['langgraph'] == '1.2.16'
        modules = [('langgraph', langgraph),
                   ('langgraph.checkpoint.sqlite', langgraph.checkpoint.sqlite),
                   ('langchain_core', langchain_core)]
        module_hashes = {}
        for name, module in modules:
            file = getattr(module, '__file__', None)
            if file:
                module_hashes[name] = dict(path=file, sha256=sha(Path(file)))
        save(run_dir / 'installation.json', dict(versions=versions, prefix=sys.prefix,
             modules=module_hashes))
        results, failures = [], []
        for case in config:
            for seed in JITTER:
                gate, initial = JITTER[seed]
                os.environ['R1_GATE_DELAY_S'] = str(gate)
                os.environ['R1_INITIAL_TIMEOUT'] = str(initial)
                import r3_langgraph
                r3_langgraph.GATE_DELAY_S = gate
                r3_langgraph.INITIAL_TIMEOUT = initial
                directory = run_dir / f'S{seed}_{case["id"]}'
                try:
                    result = run(directory, case['route'], case['change'], case['fault'], seed)
                    results.append(dict(case=case['id'], seed=seed, terminal=result['terminal'],
                                        duplicate=result['duplicate'], rows=result['rows'],
                                        stale_new=result['stale_new'],
                                        elapsed_ns=result['elapsed_ns']))
                except BaseException as error:
                    failures.append(dict(case=case['id'], seed=seed,
                                         type=type(error).__name__, message=str(error),
                                         traceback=traceback.format_exc()))
        save(run_dir / 'completion.json', dict(tasks=results, failures=failures, sealed={
            path.relative_to(run_dir).as_posix(): sha(path) for path in run_dir.rglob('*')
            if path.is_file() and 'snapshots' not in path.parts and path.name != 'completion.json'}))
    except BaseException as error:
        save(run_dir / 'failure.json', dict(type=type(error).__name__, message=str(error),
                                            traceback=traceback.format_exc()))
        raise


if __name__ == '__main__':
    main()
