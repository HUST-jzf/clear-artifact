"""Freeze and run R4 holdout: 8 conditions × 5 policies on one new framework."""
import argparse
import hashlib
import importlib
import importlib.metadata
import json
import platform
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import r4_holdout

POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']
SEED_PARAMS = {0: (0.080, 0.060, 0.150), 1: (0.072, 0.052, 0.145),
               2: (0.076, 0.054, 0.150), 3: (0.084, 0.056, 0.140),
               4: (0.068, 0.050, 0.142), 5: (0.074, 0.053, 0.148),
               6: (0.078, 0.055, 0.152), 7: (0.082, 0.057, 0.144),
               8: (0.086, 0.058, 0.146), 9: (0.090, 0.059, 0.150)}
SOURCES = {
    'smolagents': dict(dir='R4_smolagents', distribution='smolagents', version='1.26.0',
                       module='smolagents', adapter=r4_holdout.SmolagentsAdapter,
                       files=['sources/R4_smolagents/wheels_sha256.json',
                              'sources/R4_smolagents/static_review.md']),
    'pydantic_ai': dict(dir='R4_pydantic_ai', distribution='pydantic-ai-slim', version='2.59.0',
                        module='pydantic_ai', adapter=r4_holdout.PydanticAIAdapter,
                        files=['sources/R4_pydantic_ai/wheels_sha256.json',
                               'sources/R4_pydantic_ai/static_review.md']),
    'llamaindex': dict(dir='R4_llamaindex', distribution='llama-index-core', version='0.14.25',
                       module='llama_index.core', adapter=r4_holdout.LlamaIndexAdapter,
                       files=['sources/R4_llamaindex/wheels_sha256.json',
                              'sources/R4_llamaindex/static_review.md']),
    'autogen': dict(dir='R4_autogen', distribution='autogen-core', version='0.7.5',
                    module='autogen_core', adapter=r4_holdout.AutoGenAdapter,
                    files=['sources/R4_autogen/wheels_sha256.json',
                           'sources/R4_autogen/static_review.md']),
}


def condition(name, patch=None, **changes):
    route = dict(revision=1, mode='inline', outcome='fail', delayed=False,
                 abandon_on_cancel=False, delegated=False, closed_registration=True,
                 allowed=True, store='effects', idempotency=False, query_complete=True)
    route.update(changes)
    return dict(id=name, route=route, patch=patch)


CASES = [
    condition('C01_fail_before'),
    condition('C02_lost_return', outcome='commit'),
    condition('C03_late_commit', outcome='commit', delayed=True),
    condition('C04_revoke', patch={'allowed': False}),
    condition('C05_query_unavailable', outcome='commit', query_complete=False,
              closed_registration=False),
    condition('C06_closure_missing', outcome='commit', closed_registration=False),
    condition('C07_idempotent_lost', outcome='commit', idempotency=True),
    condition('C08_normal', outcome='commit'),
]
EXPECTED = {
    'C01_fail_before': dict(terminal='complete', rows=1),
    'C02_lost_return': dict(terminal='complete', rows=1),
    'C03_late_commit': dict(terminal='complete', rows=1),
    'C04_revoke': dict(terminal='pause', rows=0),
    'C05_query_unavailable': dict(terminal='pause', rows=1),
    'C06_closure_missing': dict(terminal='complete', rows=1),
    'C07_idempotent_lost': dict(terminal='complete', rows=1),
    'C08_normal': dict(terminal='complete', rows=1),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


async def task(run, source, case, policy):
    from r1_policies import run as control
    host = r4_holdout.Host(run / f"{case['id']}_{policy}", case['route'],
                           SOURCES[source]['adapter'], case['patch'])
    result = None
    try:
        await host.start()
        result = await control(host, policy)
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
    return dict(case=case['id'], policy=policy, terminal=result['terminal'],
                reason=result['reason'], actions=len(result['events']),
                elapsed_ns=result['elapsed_ns'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, choices=sorted(SOURCES))
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--seed', type=int, default=0, choices=sorted(SEED_PARAMS))
    args = parser.parse_args()
    source = SOURCES[args.source]
    gate, timeout, wait = SEED_PARAMS[args.seed]
    r4_holdout.GATE_DELAY_S = gate
    r4_holdout.INITIAL_TIMEOUT = timeout
    r4_holdout.WAIT_WINDOW = wait
    run_dir = ROOT / 'runs' / source['dir'] / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    names = ['docs/R4_held_out_sources_protocol.md', 'docs/R14_extended_held_out_sources_protocol.md',
             'scripts/r4_holdout.py',
             'scripts/run_r4.py', 'scripts/verify_r4.py', 'scripts/r1_policies.py'] + source['files']
    hashes = {}
    for name in names:
        src, dest = ROOT / name, run_dir / 'snapshots' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        hashes[name] = sha(src)
    save(run_dir / 'freeze.json', dict(source=args.source, files=hashes, cases=CASES,
         policies=POLICIES, expected=EXPECTED, idempotency="per case", seed=args.seed,
         seed_params=dict(gate_s=gate, initial_timeout_s=timeout, wait_window_s=wait),
         target_calls_before_freeze=0, python=sys.executable,
         python_version=platform.python_version(), created_ns=time.time_ns()))
    try:
        import anyio
        import clear_assurance
        versions = {name: importlib.metadata.version(name)
                    for name in ['clear-assurance', source['distribution']]}
        assert versions['clear-assurance'] == '2.0.0'
        assert versions[source['distribution']] == source['version']
        module = importlib.import_module(source['module'])
        save(run_dir / 'installation.json', dict(versions=versions, prefix=sys.prefix,
             package=clear_assurance.__file__,
             modules={module.__name__: dict(path=module.__file__,
                                            sha256=sha(Path(module.__file__)))}))
        results, failures = [], []
        for case in CASES:
            for policy in POLICIES:
                try:
                    results.append(anyio.run(task, run_dir, args.source, case, policy))
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
