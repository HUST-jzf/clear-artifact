"""Freeze and run R13 change-after-evidence campaign on one source."""
import argparse
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
import r13_change

POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']
SEEDS = list(range(20))
SOURCES = {
    'anyio': dict(dir='R13_anyio', versions=['clear-assurance', 'anyio'],
                  expect={'anyio': '4.12.1'}, files=['scripts/r1_anyio.py']),
    'langchain': dict(dir='R13_langchain',
                      versions=['clear-assurance', 'langchain-core', 'anyio'],
                      expect={'langchain-core': '1.0.0', 'anyio': '4.15.1'},
                      files=['scripts/r1_anyio.py', 'scripts/r1_langchain.py']),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, choices=sorted(SOURCES))
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--seeds', default='0-19')
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    source = SOURCES[args.source]
    run_dir = ROOT / 'runs' / source['dir'] / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    names = ['docs/R13_post_change_recovery_protocol.md', 'scripts/r13_change.py',
             'scripts/run_r13.py', 'scripts/verify_r13.py', 'scripts/r1_policies.py'] \
            + source['files']
    hashes = {}
    for name in names:
        src, dest = ROOT / name, run_dir / 'snapshots' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        hashes[name] = sha(src)
    cases = [dict(id=f'{mode}_S{seed}', mode=mode, seed=seed)
             for mode in r13_change.MODES for seed in seeds]
    save(run_dir / 'freeze.json', dict(source=args.source, files=hashes, cases=cases,
         policies=POLICIES, seeds=seeds, modes=r13_change.MODES, idempotency=False,
         query_complete=True, closure=True, target_calls_before_freeze=0,
         python=sys.executable, python_version=platform.python_version(),
         created_ns=time.time_ns()))
    try:
        import anyio
        import clear_assurance
        versions = {name: importlib.metadata.version(name) for name in source['versions']}
        for name, expected in source['expect'].items():
            assert versions[name] == expected, (name, versions[name], expected)
        assert versions['clear-assurance'] == '2.0.0'
        save(run_dir / 'installation.json', dict(versions=versions, prefix=sys.prefix,
             package=clear_assurance.__file__))
        results, failures = [], []
        for case in cases:
            for policy in POLICIES:
                try:
                    results.append(anyio.run(r13_change.task, run_dir, args.source, case, policy))
                except BaseException as error:
                    failures.append(dict(case=case['id'], policy=policy,
                                         type=type(error).__name__, message=str(error),
                                         traceback=traceback.format_exc()))
        save(run_dir / 'completion.json', dict(tasks=results, failures=failures, sealed={
            path.relative_to(run_dir).as_posix(): sha(path) for path in run_dir.rglob('*')
            if path.is_file() and 'snapshots' not in path.parts
            and path.name != 'completion.json' and not path.name.endswith('.sqlite')}))
    except BaseException as error:
        save(run_dir / 'failure.json', dict(type=type(error).__name__, message=str(error),
                                            traceback=traceback.format_exc()))
        raise


if __name__ == '__main__':
    main()
