"""R48: framework replay x cancel propagation x remote stop x closure evidence.

The controller gives up after the first timeout, optionally cancels, optionally
waits for closure evidence, and optionally replays the step.  Duplicates are
counted from the executor's own database.
"""
import argparse
import hashlib
import http.client
import json
import platform
import subprocess
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
POST_TIMEOUT = 0.3
GET_TIMEOUT = 0.6
LATE_DELAY = 0.9
FAULTS = ['lost_return', 'late_commit']
NAMES = ['docs/R48_cross_layer_closure_protocol_20261029.md', 'scripts/r48_service.py',
         'scripts/run_r48.py', 'scripts/verify_r48.py']


class Client:
    def __init__(self, base_url):
        parts = urlsplit(base_url)
        self.host, self.port = parts.hostname, parts.port

    def request(self, method, path, body=None, timeout=GET_TIMEOUT):
        payload = json.dumps(body).encode() if body is not None else None
        connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            connection.request(method, path, body=payload,
                               headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            data = response.read()
            return dict(ok=response.status < 400, status=response.status,
                        body=json.loads(data or b'{}'))
        except (OSError, http.client.HTTPException) as error:
            return dict(ok=False, status=None, body={}, error=type(error).__name__)
        finally:
            connection.close()

    def attach(self, workflow, op, attempt):
        body = dict(op=op, attempt=attempt)
        return self.request('POST', f'/w/{workflow}/attach', body, POST_TIMEOUT)

    def cancel(self, workflow, op, attempt=1):
        return self.request('POST', f'/w/{workflow}/cancel',
                            dict(op=op, attempt=attempt))

    def lifecycle(self, workflow, op):
        return self.request('GET', f'/w/{workflow}/ops/{op}')

    def stop(self):
        return self.request('POST', '/control/stop', {})


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8')


def wait_ready(directory, process, limit=30.0):
    deadline = time.time() + limit
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'service exited with {process.returncode}')
        path = directory / 'ready.json'
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))['base_url']
        time.sleep(0.02)
    raise RuntimeError('service did not become ready')


def observe(client, workflow, op, limit=2.0):
    deadline = time.monotonic() + limit
    body = dict(state='pending', terminal=False, receipt=None)
    while time.monotonic() < deadline:
        response = client.lifecycle(workflow, op)
        body = dict(response.get('body') or {})
        if body.get('terminal'):
            return body
        time.sleep(0.02)
    return body


def run_workflow(client, workflow, replay, cancel, closure, fault):
    op = f'{workflow}:attach'
    first = client.attach(workflow, op, 1)
    completed = bool(first['ok'] and first['body'].get('state') == 'committed')
    if cancel:
        client.cancel(workflow, op)
    if not completed and closure:
        body = observe(client, workflow, op)
        completed = bool(body.get('receipt') is not None)
    if not completed and replay:
        second = client.attach(workflow, op, 2)
        completed = bool(second['ok'] and second['body'].get('state') == 'committed')
    return dict(completed=completed, terminal='complete' if completed else 'pause')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--seeds', default='0-9')
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    run = ROOT / 'runs' / 'R48' / args.attempt
    run.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        source = ROOT / name
        if not source.exists():
            continue
        destination = run / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        hashes[name] = sha(source)
    save(run / 'freeze.json', dict(files=hashes, faults=FAULTS,
                                   factors=['replay', 'cancel', 'stop', 'closure'],
                                   seeds=seeds, post_timeout_s=POST_TIMEOUT,
                                   get_timeout_s=GET_TIMEOUT, late_delay_s=LATE_DELAY,
                                   python=sys.executable,
                                   python_version=platform.python_version(),
                                   created_ns=time.time_ns()))
    tasks, failures = [], []
    for closure in ('on', 'off'):
        for stop in ('on', 'off'):
            directory = run / f'closure_{closure}_stop_{stop}'
            directory.mkdir()
            faults = {}
            for replay in ('on', 'off'):
                for cancel in ('on', 'off'):
                    for fault in FAULTS:
                        for seed in seeds:
                            workflow = f'R_{replay}_C_{cancel}_S_{stop}_L_{closure}_{fault}_s{seed}'
                            faults[workflow] = {'attach': dict(kind=fault,
                                                               delay=LATE_DELAY)}
            save(directory / 'faults.json', faults)
            log = (directory / 'service.log').open('w', encoding='utf-8')
            process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/r48_service.py'),
                                        '--run-root', str(directory),
                                        '--stop', stop, '--closure', closure],
                                       cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
            try:
                base = wait_ready(directory, process)
                client = Client(base)
                for replay in ('on', 'off'):
                    for cancel in ('on', 'off'):
                        for fault in FAULTS:
                            for seed in seeds:
                                workflow = (f'R_{replay}_C_{cancel}_S_{stop}_L_{closure}_'
                                            f'{fault}_s{seed}')
                                try:
                                    started = time.perf_counter_ns()
                                    outcome = run_workflow(client, workflow, replay == 'on',
                                                           cancel == 'on', closure == 'on',
                                                           fault)
                                    tasks.append(dict(
                                        replay=replay, cancel=cancel, stop=stop,
                                        closure=closure, fault=fault, seed=seed,
                                        workflow=workflow,
                                        terminal=outcome['terminal'],
                                        elapsed_ns=time.perf_counter_ns() - started))
                                except BaseException as error:
                                    failures.append(dict(
                                        workflow=workflow, type=type(error).__name__,
                                        message=str(error),
                                        traceback=traceback.format_exc()))
                time.sleep(LATE_DELAY + 0.3)
                client.stop()
                process.wait(timeout=30)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                log.close()
            stats = json.loads((directory / 'private' / 'stats.json')
                               .read_text(encoding='utf-8'))
            for task in tasks:
                if task['stop'] != stop or task['closure'] != closure:
                    continue
                observed = stats.get(task['workflow'], dict(effects=0, terminal=False,
                                                            state='pending'))
                task.update(effects=int(observed['effects']),
                            duplicates=max(0, int(observed['effects']) - 1),
                            state=observed['state'],
                            complete=(task['terminal'] == 'complete'
                                      and int(observed['effects']) == 1))
    save(run / 'completion.json', dict(tasks=tasks, failures=failures, seeds=seeds,
                                       faults=FAULTS))
    print(json.dumps(dict(tasks=len(tasks), failures=len(failures))))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
