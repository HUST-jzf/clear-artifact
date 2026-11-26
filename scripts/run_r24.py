"""R24: can a CLEAR pause be resumed, and is replay-safe resumption a real problem?

Two operator conditions are injected per workflow:

* `revoke_at_attach` - the permit is revoked after `reserve` commits; the operator
  restores it (`POST /w/{wf}/repair`, epoch+1).
* `blackout_at_attach` - `attach` commits but its response is lost, and both
  evidence endpoints return 503 until the operator repairs the store.

Four policies: `clear` (pause is terminal), `clear_replay` (repair, then replay the
paused step), `clear_resume` (repair, then re-read evidence before writing), and
`idem_retry` as a reference. Idempotency is off so duplicates are visible.
"""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import r19_client as base
import r24_client as r24

POLICIES = ['clear', 'clear_replay', 'clear_resume', 'idem_retry']
CONDITIONS = {
    'revoke_at_attach': dict(kind='revoke', step='attach'),
    'blackout_at_attach': dict(kind='blackout', step='attach'),
}
NAMES = ['docs/R24_recoverable_pause_protocol.md', 'scripts/r24_service.py',
         'scripts/r19_client.py', 'scripts/r24_client.py', 'scripts/run_r24.py',
         'scripts/verify_r24.py']


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
            return json.loads(path.read_text(encoding='utf-8'))['base_url']
        time.sleep(0.05)
    raise RuntimeError('service did not become ready')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--seeds', default='0-19')
    parser.add_argument('--policies', default=','.join(POLICIES))
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    policies = [item for item in args.policies.split(',') if item]
    run_dir = ROOT / 'runs' / 'R24' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        destination = run_dir / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
        hashes[name] = sha(ROOT / name)
    save(run_dir / 'freeze.json', dict(
        config='idem_off', policies=policies, seeds=seeds,
        conditions=CONDITIONS, idempotency='off', lifecycle='faithful',
        query_mode='faithful', steps=base.STEPS, files=hashes,
        post_timeout_s=base.POST_TIMEOUT, get_timeout_s=base.GET_TIMEOUT,
        dispatch_jitter_s=base.JITTER, python=sys.executable,
        python_version=platform.python_version(), service='r24_service.py',
        target_calls_before_freeze=0, created_ns=time.time_ns()))
    save(run_dir / 'installation.json', dict(
        python=sys.executable, python_version=platform.python_version(),
        prefix=sys.prefix,
        versions={'clear-assurance': importlib.metadata.version('clear-assurance')}))
    directory = run_dir / 'idem_off'
    directory.mkdir()
    faults = {}
    for condition in CONDITIONS:
        for seed in seeds:
            for policy in policies:
                workflow = f'{condition}_S{seed}_{policy}'
                if conditions_blackout(condition):
                    faults[workflow] = {'attach': dict(kind='lost_return')}
    save(directory / 'faults.json', faults, exclusive=False)
    save(directory / 'conditions.json',
         {f'{condition}_S{seed}_{policy}': dict(CONDITIONS[condition])
          for condition in CONDITIONS for seed in seeds for policy in policies},
         exclusive=False)
    (directory / 'idempotency').write_text('off', encoding='utf-8')
    (directory / 'lifecycle').write_text('faithful', encoding='utf-8')
    (directory / 'query_mode').write_text('faithful', encoding='utf-8')
    results, failures = [], []
    log = (directory / 'service.log').open('w', encoding='utf-8')
    process = subprocess.Popen(
        [sys.executable, str(ROOT / 'scripts' / 'r24_service.py'),
         '--run-root', str(directory)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    try:
        base_url = wait_ready(directory, process)
        started = time.perf_counter_ns()
        for condition in CONDITIONS:
            for policy in policies:
                for seed in seeds:
                    workflow = f'{condition}_S{seed}_{policy}'
                    try:
                        client = r24.Client(base_url)
                        result = r24.run_workflow(client, workflow, policy, seed, condition)
                        result.update(config='idem_off', condition=condition, policy=policy,
                                      seed=seed, workflow=workflow)
                        results.append(result)
                    except BaseException as error:
                        failures.append(dict(workflow=workflow, condition=condition,
                                             policy=policy, seed=seed,
                                             type=type(error).__name__,
                                             message=str(error),
                                             traceback=traceback.format_exc()))
        wall_ns = time.perf_counter_ns() - started
        base.Client(base_url).stop()
    finally:
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()
    save(directory / 'service.json', dict(
        base_url=base_url, pid=process.pid, returncode=process.returncode,
        idempotency='off', evidence_mode='faithful'))
    save(run_dir / 'completion.json', dict(
        configs=['idem_off'], policies=policies, conditions=list(CONDITIONS),
        seeds=seeds, tasks=results, failures=failures,
        wall_s=round(wall_ns / 1e9, 3),
        sealed={path.relative_to(run_dir).as_posix(): sha(path)
                for path in run_dir.rglob('*')
                if path.is_file() and 'snapshots' not in path.parts
                and 'private' not in path.parts
                and not path.name.endswith('.sqlite')
                and path.name not in ('completion.json', 'service.log')}))


def conditions_blackout(condition):
    return CONDITIONS[condition]['kind'] == 'blackout'


if __name__ == '__main__':
    main()
