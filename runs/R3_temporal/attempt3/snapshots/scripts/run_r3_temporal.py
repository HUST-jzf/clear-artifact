"""Run R3 Temporal workflow/activity-retry baseline on 12 capability cells × 10 seeds."""
import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import platform
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from r3_temporal import (EffectWorkflow, TASK_QUEUE, commit_effect, run_task)

JITTER = {
    0: (1.50, 1.20), 1: (1.42, 1.12), 2: (1.46, 1.14), 3: (1.54, 1.16),
    4: (1.38, 1.10), 5: (1.44, 1.13), 6: (1.48, 1.15), 7: (1.52, 1.17),
    8: (1.56, 1.18), 9: (1.60, 1.19),
}
PORT = 17233
CLI = ROOT / 'sources/R3_temporal/cli/temporal.exe'


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


def wait_port(port, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def start_server(run_dir):
    log = (run_dir / 'temporal_server.log').open('x', encoding='utf-8')
    proc = subprocess.Popen([str(CLI), 'server', 'start-dev', '--headless',
                             '--port', str(PORT), '--db-filename',
                             str(run_dir / 'temporal.db')],
                            stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
    if not wait_port(PORT, 40):
        proc.terminate()
        raise RuntimeError('temporal dev server did not open port')
    return proc, log


async def run_all(run_dir, config):
    from concurrent.futures import ThreadPoolExecutor
    from temporalio.client import Client
    from temporalio.worker import Worker
    client = await Client.connect(f'127.0.0.1:{PORT}', namespace='default')
    results, failures = [], []
    executor = ThreadPoolExecutor(max_workers=8)
    async with Worker(client, task_queue=TASK_QUEUE, workflows=[EffectWorkflow],
                      activities=[commit_effect], max_concurrent_activities=4,
                      activity_executor=executor):
        for case in config:
            for seed, (gate, timeout) in JITTER.items():
                directory = run_dir / f'S{seed}_{case["id"]}'
                try:
                    result = await run_task(client, directory, case['route'],
                                            case['change'], case['fault'], seed,
                                            gate, timeout)
                    results.append(dict(case=case['id'], seed=seed,
                                        terminal=result['terminal'], rows=result['rows'],
                                        duplicate=result['duplicate'],
                                        stale_new=result['stale_new'],
                                        late_original=result['late_original'],
                                        attempts=result['attempts'],
                                        elapsed_ns=result['elapsed_ns']))
                except BaseException as error:
                    failures.append(dict(case=case['id'], seed=seed,
                                         type=type(error).__name__, message=str(error),
                                         traceback=traceback.format_exc()))
        await asyncio.sleep(0.5)
    return results, failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    run_dir = ROOT / 'runs/R3_temporal' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    names = ['scripts/run_r3_temporal.py', 'scripts/r3_temporal.py',
             'docs/R3_Temporal_baseline_protocol.md']
    hashes = {}
    for name in names:
        source, dest = ROOT / name, run_dir / 'snapshots' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    config = cases()
    save(run_dir / 'freeze.json', dict(files=hashes, cases=config, seeds=list(JITTER),
         jitter={str(k): dict(gate=v[0], initial_timeout=v[1]) for k, v in JITTER.items()},
         cli=dict(version='1.9.1', server_version='1.32.0', sha256=sha(CLI)),
         wheels_sha256=sha(ROOT / 'sources/R3_temporal/wheels_sha256.json'),
         port=PORT, target_calls_before_freeze=0, python=sys.executable,
         python_version=platform.python_version(), created_ns=time.time_ns()))
    proc = log = None
    try:
        import temporalio
        versions = {'temporalio': importlib.metadata.version('temporalio')}
        assert versions['temporalio'] == '1.34.0'
        module_file = getattr(temporalio, '__file__', None)
        module_hashes = {}
        if module_file:
            module_hashes['temporalio'] = dict(path=module_file, sha256=sha(Path(module_file)))
        save(run_dir / 'installation.json', dict(versions=versions, prefix=sys.prefix,
             modules=module_hashes, server='1.32.0', cli='1.9.1'))
        proc, log = start_server(run_dir)
        results, failures = asyncio.run(run_all(run_dir, config))
        save(run_dir / 'completion.json', dict(tasks=results, failures=failures, sealed={
            path.relative_to(run_dir).as_posix(): sha(path) for path in run_dir.rglob('*')
            if path.is_file() and 'snapshots' not in path.parts
            and path.name not in ['completion.json', 'temporal.db', 'temporal.db-wal',
                                  'temporal.db-shm', 'temporal_server.log']
            and not path.name.endswith('.sqlite')}))
    except BaseException as error:
        save(run_dir / 'failure.json', dict(type=type(error).__name__, message=str(error),
                                            traceback=traceback.format_exc()))
        raise
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
        if log:
            log.close()


if __name__ == '__main__':
    main()
