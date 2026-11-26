"""Shared HTTP surface and metrics for the two R16 baselines.

Both baselines talk to the same R15 ticket service through this client; neither
imports CLEAR. Metrics are computed from the service's own state endpoint.
"""
import http.client
import json
import random
import time
from urllib.parse import urlsplit

STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
FAULTS = ['lost_return', 'late_commit', 'revoke_after_reserve', 'revoke_after_commit']
FAULT_STEP = {'lost_return': 'attach', 'late_commit': 'commit',
              'revoke_after_reserve': 'reserve', 'revoke_after_commit': 'commit'}
INTENT = {step: 'ticket:' + step for step in STEPS}
POST_TIMEOUT = 0.25
GET_TIMEOUT = 0.5
LATE_DELAY = 0.8
JITTER = 0.015


def jitters(fault, seed):
    """The same seed-derived dispatch jitter used by the R15 controllers."""
    rng = random.Random((seed + 1) * 1000033 + FAULTS.index(fault) * 7919)
    return [rng.uniform(0.0, JITTER) for _ in STEPS]


def workflow_id(baseline, config, fault, seed):
    return f'{baseline}-{config}-{fault}-S{seed}'


def save(path, value):
    with open(path, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


class ServiceClient:
    def __init__(self, base_url):
        parts = urlsplit(base_url)
        self.host, self.port = parts.hostname, parts.port
        self.post_calls = 0

    def request(self, method, path, body=None, key=None, timeout=GET_TIMEOUT):
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['Idempotency-Key'] = key
        payload = json.dumps(body).encode() if body is not None else None
        connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            data = response.read()
            return dict(ok=response.status < 400, status=response.status,
                        body=json.loads(data or b'{}'))
        except (OSError, http.client.HTTPException) as error:
            return dict(ok=False, status=None, body={}, error=type(error).__name__)
        finally:
            connection.close()

    def step(self, workflow, step, attempt, epoch):
        self.post_calls += 1
        body = dict(op=f'{workflow}:{step}', step=step, attempt=attempt,
                    permit_epoch=epoch, intent=INTENT[step])
        return self.request('POST', f'/w/{workflow}/{step}', body,
                            f'{workflow}/{step}', POST_TIMEOUT)

    def permit(self, workflow):
        return self.request('GET', f'/permit/{workflow}').get('body', {})

    def state(self, workflow):
        return self.request('GET', f'/w/{workflow}/state').get('body', {}).get('steps', {})


def metrics(client, workflow, terminal, started_ns):
    observed = client.state(workflow)
    rows = {step: int(observed.get(step, {}).get('rows', 0)) for step in STEPS}
    stale = {step: int(observed.get(step, {}).get('stale', 0)) for step in STEPS}
    completed = terminal == 'complete' and all(rows[step] >= 1 for step in STEPS)
    duplicates = sum(max(0, rows[step] - 1) for step in STEPS)
    stale_rows = sum(stale.values())
    return dict(workflow=workflow, terminal=terminal, completed=completed,
                duplicates=duplicates, stale_rows=stale_rows,
                orphan=int(not completed and rows['reserve'] >= 1),
                rows=rows, stale=stale, post_calls=client.post_calls,
                safe=(completed and duplicates == 0 and stale_rows == 0
                      and all(rows[step] == 1 for step in STEPS)),
                elapsed_ns=time.perf_counter_ns() - started_ns)
