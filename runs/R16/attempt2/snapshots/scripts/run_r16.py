"""R16: run the two fair baselines against the same ticket service.

Each baseline runs in its own frozen environment (Temporal in the R3 Temporal
environment, LangGraph in the R3 LangGraph environment) and writes its own
result file; this runner only starts/stops the service, records versions and
merges the two result sets.
"""
import argparse
import hashlib
import http.client
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import r16_common as common

PYTHON = {
    'temporal': ROOT / 'runs/R3_temporal/env/Scripts/python.exe',
    'langgraph': ROOT / 'runs/R3_langgraph/env/Scripts/python.exe',
}
SCRIPT = {'temporal': ROOT / 'scripts/r16_temporal.py',
          'langgraph': ROOT / 'scripts/r16_langgraph.py'}
MODULES = {'temporal': ['temporalio'],
           'langgraph': ['langgraph', 'langgraph-checkpoint-sqlite']}
EXPECTED = {'temporalio': '1.34.0', 'langgraph': '1.2.16',
            'langgraph-checkpoint-sqlite': '3.1.2'}
CONFIGS = ['idem_on', 'idem_off']
SEEDS = list(range(20))
NAMES = ['docs/R16_fair_baselines_protocol.md', 'scripts/r15_service.py',
         'scripts/r16_common.py', 'scripts/r16_temporal.py',
         'scripts/r16_langgraph.py', 'scripts/run_r16.py', 'scripts/verify_r16.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value, exclusive=True):
    mode = 'x' if exclusive else 'w'
    with Path(path).open(mode, encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def module_versions(python, names):
    code = ('import json,importlib.metadata as m;'
            'print(json.dumps({n: m.version(n) for n in %r}))' % (names,))
    finished = subprocess.run([str(python), '-c', code], capture_output=True, text=True)
    if finished.returncode != 0:
        raise RuntimeError(finished.stderr)
    return json.loads(finished.stdout.strip().splitlines()[-1])


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


def stop_service(base_url):
    parts = base_url.split('//', 1)[1].split(':')
    connection = http.client.HTTPConnection(parts[0], int(parts[1]), timeout=5)
    try:
        connection.request('POST', '/control/stop', body=b'{}',
                           headers={'Content-Type': 'application/json'})
        connection.getresponse().read()
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--seeds', default='0-19')
    parser.add_argument('--baselines', default='temporal,langgraph')
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    baselines = [item for item in args.baselines.split(',') if item]
    run_dir = ROOT / 'runs' / 'R16' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        source, destination = ROOT / name, run_dir / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    faults = {}
    for baseline in baselines:
        for config in CONFIGS:
            for fault in common.FAULTS:
                for seed in seeds:
                    faults[common.workflow_id(baseline, config, fault, seed)] = {
                        common.FAULT_STEP[fault]: dict(kind=fault, delay=common.LATE_DELAY)}
    save(run_dir / 'freeze.json', dict(
        baselines=baselines, configs=CONFIGS, faults=common.FAULTS,
        fault_step=common.FAULT_STEP, seeds=seeds, steps=common.STEPS,
        cases=len(faults), files=hashes, post_timeout_s=common.POST_TIMEOUT,
        get_timeout_s=common.GET_TIMEOUT, late_delay_s=common.LATE_DELAY,
        dispatch_jitter_s=common.JITTER, service_version='ticket-svc-2026.10-v1',
        temporal=dict(cli='1.9.1', server='1.32.0', sdk='1.34.0',
                      maximum_attempts=2, initial_interval_ms=10,
                      backoff_coefficient=1.0, start_to_close_timeout_ms=250),
        langgraph=dict(version='1.2.16', checkpointer='langgraph-checkpoint-sqlite 3.1.2',
                       max_attempts=2, initial_interval_s=0.01, backoff_factor=1.0,
                       jitter=False, retry_on=['ConnectionError', 'TimeoutError']),
        python=sys.executable, python_version=platform.python_version(),
        target_calls_before_freeze=0, created_ns=time.time_ns()))
    installation = {'python': sys.executable,
                    'python_version': platform.python_version(),
                    'prefix': sys.prefix,
                    'temporal_python': str(PYTHON['temporal']),
                    'langgraph_python': str(PYTHON['langgraph']),
                    'temporal_cli_sha256': sha(ROOT / 'sources/R3_temporal/cli/temporal.exe'),
                    'modules': {}}
    for baseline in baselines:
        versions = module_versions(PYTHON[baseline], MODULES[baseline])
        for name, version in versions.items():
            if name in EXPECTED:
                assert version == EXPECTED[name], (name, version, EXPECTED[name])
        installation['modules'][baseline] = versions
    save(run_dir / 'installation.json', installation)
    tasks, failures = [], []
    try:
        for config in CONFIGS:
            directory = run_dir / config
            directory.mkdir()
            save(directory / 'faults.json', faults, exclusive=False)
            (directory / 'idempotency').write_text(
                'on' if config == 'idem_on' else 'off', encoding='utf-8')
            log = (directory / 'service.log').open('w', encoding='utf-8')
            process = subprocess.Popen(
                [sys.executable, str(ROOT / 'scripts' / 'r15_service.py'),
                 '--run-root', str(directory)],
                cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
            try:
                base_url = wait_ready(directory, process)
                for baseline in baselines:
                    out = directory / f'{baseline}.json'
                    finished = subprocess.run(
                        [str(PYTHON[baseline]), str(SCRIPT[baseline]),
                         '--base-url', base_url, '--config', config,
                         '--seeds', args.seeds, '--out', str(out),
                         '--run-root', str(directory)],
                        cwd=str(ROOT), capture_output=True, text=True, timeout=3600)
                    (directory / f'{baseline}.log').write_text(
                        finished.stdout + finished.stderr, encoding='utf-8')
                    if finished.returncode != 0 or not out.exists():
                        failures.append(dict(config=config, baseline=baseline,
                                             returncode=finished.returncode,
                                             stdout=finished.stdout[-4000:],
                                             stderr=finished.stderr[-4000:]))
                        continue
                    payload = json.loads(out.read_text(encoding='utf-8'))
                    tasks.extend(payload['tasks'])
                    failures.extend(payload['failures'])
                    save(directory / f'{baseline}.policy.json',
                         {key: value for key, value in payload.items()
                          if key not in ('tasks', 'failures')}, exclusive=False)
                stop_service(base_url)
            finally:
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                log.close()
            save(directory / 'service.json', dict(
                base_url=base_url, pid=process.pid, returncode=process.returncode,
                idempotency=config == 'idem_on'))
        save(run_dir / 'completion.json', dict(
            baselines=baselines, configs=CONFIGS, seeds=seeds, tasks=tasks,
            failures=failures, sealed={
                path.relative_to(run_dir).as_posix(): sha(path) for path in run_dir.rglob('*')
                if path.is_file() and 'snapshots' not in path.parts
                and 'private' not in path.parts and 'workflows' not in path.parts
                and not path.name.endswith('.sqlite') and not path.name.endswith('.log')
                and not path.name.endswith('-wal') and not path.name.endswith('-shm')
                and path.name not in ('completion.json', 'temporal.db',
                                      'temporal_server.log')}))
    except BaseException as error:
        import traceback
        save(run_dir / 'failure.json', dict(type=type(error).__name__, message=str(error),
                                            traceback=traceback.format_exc()))
        raise


if __name__ == '__main__':
    main()
