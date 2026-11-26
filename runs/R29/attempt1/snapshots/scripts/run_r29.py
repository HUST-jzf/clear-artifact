"""R29: what does the evidence store cost per workflow?

Three sizes (25/50/100 workflows) run on fresh service instances, all with the
`clear` policy and no faults, so the measured bytes are the steady-state cost of
one safe workflow. The verifier checks that the per-workflow cost is stable across
sizes (linear growth) and records the capacity projection.
"""
import argparse
import hashlib
import importlib.metadata
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
import r19_client as base

SIZES = [25, 50, 100]
NAMES = ['docs/R29_evidence_storage_cost_protocol.md', 'scripts/r19_service.py',
         'scripts/r19_client.py', 'scripts/run_r29.py', 'scripts/verify_r29.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value, exclusive=True):
    mode = 'x' if exclusive else 'w'
    with Path(path).open(mode, encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def wait_ready(directory, process, limit=30.0):
    deadline = time.time() + limit
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'service exited early with {process.returncode}')
        path = directory / 'ready.json'
        if path.exists():
            try:
                return json.loads(path.read_text(encoding='utf-8'))['base_url']
            except (json.JSONDecodeError, KeyError):
                pass
        time.sleep(0.05)
    raise RuntimeError('service did not become ready')


def measure(directory, workflows):
    files = [path for path in (directory / 'private').glob('*')
             if path.is_file() and path.name != 'stats.json'
             and path.name != 'workflows.json']
    total = sum(path.stat().st_size for path in files)
    receipts, rows = [], []
    for path in sorted((directory / 'private').glob('*.sqlite')):
        db = sqlite3.connect(path)
        try:
            receipts += [item[0] for item in db.execute(
                'select length(receipt) from ops where receipt is not null')]
            rows += [item[0] for item in db.execute(
                'select count(*) from effects')]
        finally:
            db.close()
    return dict(workflows=workflows, files=len(files), total_bytes=total,
                bytes_per_workflow=round(total / workflows, 1),
                receipt_bytes_mean=round(sum(receipts) / len(receipts), 1),
                receipt_bytes_total=sum(receipts), receipts=len(receipts),
                effect_rows=sum(rows))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    run_dir = ROOT / 'runs' / 'R29' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        destination = run_dir / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
        hashes[name] = sha(ROOT / name)
    save(run_dir / 'freeze.json', dict(
        sizes=SIZES, policy='clear', faults=[], idempotency='on',
        lifecycle='faithful', query_mode='faithful', steps=base.STEPS,
        files=hashes, python=sys.executable,
        python_version=platform.python_version(), service='r19_service.py',
        target_calls_before_freeze=0, created_ns=time.time_ns()))
    save(run_dir / 'installation.json', dict(
        python=sys.executable, python_version=platform.python_version(),
        prefix=sys.prefix,
        versions={'clear-assurance': importlib.metadata.version('clear-assurance')}))
    results, storage, failures = [], [], []
    for size in SIZES:
        config = f'n{size}'
        directory = run_dir / config
        directory.mkdir()
        save(directory / 'faults.json', {}, exclusive=False)
        (directory / 'idempotency').write_text('on', encoding='utf-8')
        (directory / 'lifecycle').write_text('faithful', encoding='utf-8')
        (directory / 'query_mode').write_text('faithful', encoding='utf-8')
        log = (directory / 'service.log').open('w', encoding='utf-8')
        process = subprocess.Popen(
            [sys.executable, str(ROOT / 'scripts' / 'r19_service.py'),
             '--run-root', str(directory)],
            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
        try:
            base_url = wait_ready(directory, process)
            for seed in range(size):
                workflow = f'normal_S{seed}_clear'
                try:
                    client = base.Client(base_url)
                    result = base.run_workflow(client, workflow, 'clear', 'lost_return', seed)
                    result.update(config=config, size=size, policy='clear', seed=seed,
                                  workflow=workflow, fault='none')
                    results.append(result)
                except BaseException as error:
                    failures.append(dict(workflow=workflow, config=config, seed=seed,
                                         type=type(error).__name__, message=str(error),
                                         traceback=traceback.format_exc()))
            base.Client(base_url).stop()
        finally:
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            log.close()
        storage.append(dict(config=config, size=size, **measure(directory, size)))
        save(directory / 'service.json', dict(base_url=base_url, pid=process.pid,
                                              returncode=process.returncode,
                                              idempotency='on'))
    save(run_dir / 'completion.json', dict(
        sizes=SIZES, policy='clear', tasks=results, failures=failures,
        storage=storage,
        sealed={path.relative_to(run_dir).as_posix(): sha(path)
                for path in run_dir.rglob('*')
                if path.is_file() and 'snapshots' not in path.parts
                and 'private' not in path.parts
                and not path.name.endswith('.sqlite')
                and path.name not in ('completion.json', 'service.log')}))


if __name__ == '__main__':
    main()
