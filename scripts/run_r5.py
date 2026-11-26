"""Run R5 concurrency/revocation race: 4 cells × 5 policies × 20 seeds."""
import argparse
import hashlib
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from r5_admission import run

POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']
SEEDS = list(range(20))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    run_dir = ROOT / 'runs/R5' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    names = ['scripts/run_r5.py', 'scripts/r5_admission.py',
             'docs/R5_concurrent_retry_revocation_protocol.md']
    hashes = {}
    for name in names:
        source, dest = ROOT / name, run_dir / 'snapshots' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    cells = [dict(change=change, idempotency=idem)
             for change in ['none', 'revoke'] for idem in [0, 1]]
    save(run_dir / 'freeze.json', dict(files=hashes, cells=cells, policies=POLICIES,
         seeds=SEEDS, controllers_per_task=2, created_ns=time.time_ns()))
    results, failures = [], []
    try:
        for cell in cells:
            for policy in POLICIES:
                for seed in SEEDS:
                    directory = run_dir / f"S{seed}_G{cell['change']}I{cell['idempotency']}_{policy}"
                    try:
                        body = run(directory, cell['change'], cell['idempotency'],
                                   policy, seed)
                        results.append(dict(case=body['case'], policy=policy, seed=seed,
                                            terminal=body['terminal'], rows=body['rows'],
                                            duplicate=body['duplicate'],
                                            stale_new=body['stale_new'],
                                            aborted=body['aborted'],
                                            errors=body['errors'],
                                            elapsed_ns=body['elapsed_ns']))
                    except BaseException as error:
                        failures.append(dict(case=cell, policy=policy, seed=seed,
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
