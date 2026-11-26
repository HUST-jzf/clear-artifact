"""R33: the steady-state cost of R22, measured across emulated WAN round trips.

The same no-fault workload runs behind a byte-forwarding proxy that delays each
direction by 1 / 10 / 40 ms (RTT 2 / 20 / 80 ms). CLEAR spends five extra round
trips per workflow, so its latency penalty over `idem_retry` should grow with the
RTT while the safety numbers stay unchanged.
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
import r21_client as r21

POLICIES = list(base.POLICIES)
RTTS = [1, 20, 80]
NAMES = ['docs/R33_wan_cost_protocol.md', 'scripts/r21_service.py',
         'scripts/r19_client.py', 'scripts/r21_client.py', 'scripts/r33_proxy.py',
         'scripts/run_r33.py', 'scripts/verify_r33.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value, exclusive=True):
    mode = 'x' if exclusive else 'w'
    with Path(path).open(mode, encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def wait(path, process, limit=30.0):
    deadline = time.time() + limit
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'process exited early with {process.returncode}')
        if path.exists():
            try:
                return json.loads(path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, KeyError):
                pass
        time.sleep(0.05)
    raise RuntimeError(f'{path.name} was not produced')


def percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--seeds', default='0-9')
    parser.add_argument('--rtts', default=','.join(str(item) for item in RTTS))
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    rtts = [int(item) for item in args.rtts.split(',') if item]
    run_dir = ROOT / 'runs' / 'R33' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        destination = run_dir / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
        hashes[name] = sha(ROOT / name)
    save(run_dir / 'freeze.json', dict(
        rtts=rtts, policies=POLICIES, seeds=seeds, faults=[], idempotency='on',
        lifecycle='faithful', query_mode='faithful', steps=base.STEPS,
        files=hashes, post_timeout_s=r21.POST_TIMEOUT,
        read_timeout_s=r21.READ_TIMEOUT, dispatch_jitter_s=base.JITTER,
        python=sys.executable, python_version=platform.python_version(),
        service='r21_service.py', target_calls_before_freeze=0,
        created_ns=time.time_ns()))
    save(run_dir / 'installation.json', dict(
        python=sys.executable, python_version=platform.python_version(),
        prefix=sys.prefix,
        versions={'clear-assurance': importlib.metadata.version('clear-assurance')}))
    results, systems, failures = [], [], []
    for rtt in rtts:
        config = f'rtt{rtt}'
        directory = run_dir / config
        directory.mkdir()
        save(directory / 'faults.json', {}, exclusive=False)
        (directory / 'idempotency').write_text('on', encoding='utf-8')
        (directory / 'lifecycle').write_text('faithful', encoding='utf-8')
        (directory / 'query_mode').write_text('faithful', encoding='utf-8')
        log = (directory / 'service.log').open('w', encoding='utf-8')
        process = subprocess.Popen(
            [sys.executable, str(ROOT / 'scripts' / 'r21_service.py'),
             '--run-root', str(directory)],
            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
        proxy_log = (directory / 'proxy.log').open('w', encoding='utf-8')
        proxy = None
        try:
            service = wait(directory / 'ready.json', process)
            port = int(service['base_url'].rsplit(':', 1)[1])
            proxy = subprocess.Popen(
                [sys.executable, str(ROOT / 'scripts' / 'r33_proxy.py'),
                 '--target-port', str(port), '--delay-ms', str(rtt / 2),
                 '--ready', str(directory / 'proxy.json')],
                cwd=str(ROOT), stdout=proxy_log, stderr=subprocess.STDOUT)
            info = wait(directory / 'proxy.json', proxy)
            base_url = f"http://127.0.0.1:{info['port']}"
            started = time.perf_counter_ns()
            for policy in POLICIES:
                for seed in seeds:
                    workflow = f'normal_S{seed}_{policy}'
                    try:
                        client = r21.Client(base_url)
                        try:
                            result = base.run_workflow(client, workflow, policy,
                                                       'lost_return', seed)
                        finally:
                            client.close()
                        result.update(config=config, rtt=rtt, policy=policy,
                                      seed=seed, workflow=workflow, fault='none')
                        results.append(result)
                    except BaseException as error:
                        failures.append(dict(workflow=workflow, config=config,
                                             policy=policy, seed=seed,
                                             type=type(error).__name__,
                                             message=str(error),
                                             traceback=traceback.format_exc()))
            wall_ns = time.perf_counter_ns() - started
            systems.append(dict(config=config, rtt=rtt,
                                workflows=len(POLICIES) * len(seeds),
                                wall_s=round(wall_ns / 1e9, 3),
                                throughput=round(len(POLICIES) * len(seeds) * 1e9 / wall_ns, 3),
                                failures=len([f for f in failures if f['config'] == config])))
            base.Client(service['base_url']).stop()
        finally:
            for handle in (proxy, process):
                if handle is None:
                    continue
                try:
                    handle.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    handle.kill()
                    handle.wait()
            log.close()
            proxy_log.close()
        save(directory / 'service.json', dict(base_url=base_url, pid=process.pid,
                                              returncode=process.returncode,
                                              rtt=rtt, idempotency='on'))
    save(run_dir / 'completion.json', dict(
        rtts=rtts, policies=POLICIES, seeds=seeds, tasks=results,
        failures=failures, systems=systems,
        sealed={path.relative_to(run_dir).as_posix(): sha(path)
                for path in run_dir.rglob('*')
                if path.is_file() and 'snapshots' not in path.parts
                and 'private' not in path.parts
                and not path.name.endswith('.sqlite')
                and path.name not in ('completion.json', 'service.log', 'proxy.log')}))


if __name__ == '__main__':
    main()
