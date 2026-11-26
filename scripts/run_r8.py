"""Run R8 ablation: 9 conditions × 5 variants × 10 seeds."""
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
from r8_ablation import Host, control

VARIANTS = ['full', 'no_closure', 'no_query', 'no_version', 'no_atomic']
SEEDS = list(range(10))


def condition(name, patch=None, **changes):
    route = dict(revision=1, schema='v1', allowed=True, outcome='commit', delayed=False,
                 closed_registration=True, query_complete=True, idempotency=False)
    route.update(changes)
    return dict(id=name, route=route, patch=patch)


CASES = [
    condition('normal'),
    condition('fail_before', outcome='fail'),
    condition('lost_return'),
    condition('late_commit', delayed=True),
    condition('revoke', outcome='fail', allowed=False, revision=2),
    condition('manifest_change', outcome='fail', patch={'schema': 'v2'}),
    condition('query_unavailable', query_complete=False, closed_registration=False),
    condition('late_closure', delayed=True, closed_registration=False),
    condition('atomic_revoke', outcome='fail', race_revoke=True),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


async def task(run_dir, case, variant, seed):
    directory = run_dir / f"S{seed}_{case['id']}_{variant}"
    host = Host(directory, case['route'], case['patch'])
    result = None
    try:
        await host.start()
        result = await control(host, variant)
        result.update(case=case['id'], variant=variant, seed=seed)
        save(directory / 'result.json', result)
    except BaseException as error:
        save(directory / 'failure.json', dict(type=type(error).__name__, message=str(error),
                                              traceback=traceback.format_exc()))
        raise
    finally:
        await host.drain()
        await host.save()
    state = json.loads((directory / 'state.json').read_text(encoding='utf-8'))
    writes = state['writes']
    launch = json.loads((directory / 'native.json').read_text(encoding='utf-8'))['launch']
    stale_permit = [w for w in writes if w['believed_allowed'] and not w['allowed']]
    stale_manifest = [w for w in writes if int(w['attempt']) > 1
                      and w['schema'] != case['route'].get('schema')]
    rows = len(writes)
    return dict(case=case['id'], variant=variant, seed=seed,
                terminal=result['terminal'], reason=result['reason'],
                rows=rows, duplicate=rows > 1,
                stale_permit=len(stale_permit), stale_manifest=len(stale_manifest),
                false_complete=result['terminal'] == 'complete' and rows == 0,
                safe=result['terminal'] == 'complete' and rows == 1
                and not stale_permit and not stale_manifest)


async def main_async(run_dir):
    results, failures = [], []
    for seed in SEEDS:
        for case in CASES:
            for variant in VARIANTS:
                try:
                    results.append(await task(run_dir, case, variant, seed))
                except BaseException as error:
                    failures.append(dict(case=case['id'], variant=variant, seed=seed,
                                         type=type(error).__name__, message=str(error),
                                         traceback=traceback.format_exc()))
    return results, failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    run_dir = ROOT / 'runs/R8' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    names = ['docs/R8_component_ablation_protocol.md', 'scripts/r8_ablation.py',
             'scripts/run_r8.py', 'scripts/verify_r8.py']
    hashes = {}
    for name in names:
        src, dest = ROOT / name, run_dir / 'snapshots' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        hashes[name] = sha(src)
    save(run_dir / 'freeze.json', dict(files=hashes, cases=CASES, variants=VARIANTS,
         seeds=SEEDS, python=sys.executable, python_version=platform.python_version(),
         created_ns=time.time_ns()))
    try:
        import anyio
        import clear_assurance
        versions = {name: importlib.metadata.version(name)
                    for name in ['clear-assurance', 'anyio']}
        assert versions['clear-assurance'] == '2.0.0'
        save(run_dir / 'installation.json', dict(versions=versions, prefix=sys.prefix,
             package=clear_assurance.__file__, anyio=anyio.__file__))
        results, failures = anyio.run(main_async, run_dir)
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
