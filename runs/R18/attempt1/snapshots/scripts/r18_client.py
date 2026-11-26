"""R18 controller: five-step workflow over the split evidence surfaces.

`wait` reads the faithful lifecycle registry; `query` reads the effect index,
which may be faithful, stale or unavailable. Configuration of that capability is
server-side and identical for every controller.
"""
import hashlib
import http.client
import json
import platform
import random
import time
from pathlib import Path
from urllib.parse import urlsplit

from clear_assurance.core import decide, digest, inspect, positive

STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']
FAULTS = ['lost_return', 'late_commit']
FAULT_STEP = {'lost_return': 'attach', 'late_commit': 'commit'}
SERVICE_VERSION = 'ticket-svc-2026.10-v1'
INTENT = {step: 'ticket:' + step for step in STEPS}
CAPABILITIES = dict(executor_handle=True, closed_registration=True)
POST_TIMEOUT = 0.25
GET_TIMEOUT = 0.5
LATE_DELAY = 0.8
JITTER = 0.015
HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


SOURCE = dict(adapter='ticket-http', python=platform.python_version(), framework='stdlib-http',
              worker_sha256=sha(HERE / 'r18_service.py'),
              host_sha256=sha(HERE / 'r18_client.py'),
              observer_sha256=sha(HERE / 'run_r18.py'))


def manifest_of(service):
    return dict(SOURCE, version=service.get('version'), service_sha256=service.get('sha'))


def workflow_id(fault, seed, policy):
    return f'{fault}_S{seed}_{policy}'


def route_of(permit):
    return dict(mode='inline', closed_registration=True,
                allowed=permit.get('allowed') is True, store='effects')


class Client:
    def __init__(self, base_url):
        parts = urlsplit(base_url)
        self.host, self.port = parts.hostname, parts.port
        self.http_calls = 0
        self.post_calls = 0

    def request(self, method, path, body=None, key=None, timeout=GET_TIMEOUT):
        self.http_calls += 1
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

    def describe(self):
        return self.request('GET', '/manifest')

    def manifest(self):
        return manifest_of(self.describe().get('body', {}).get('manifest', {}))

    def permit(self, workflow):
        return self.request('GET', f'/permit/{workflow}')

    def reauthorize(self, workflow):
        return self.request('POST', f'/w/{workflow}/reauthorize', {})

    def state(self, workflow):
        return self.request('GET', f'/w/{workflow}/state')

    def lifecycle(self, workflow, step):
        return self.request('GET', f'/w/{workflow}/ops/{workflow}:{step}')

    def effects(self, workflow, step):
        return self.request('GET', f'/w/{workflow}/ops/{workflow}:{step}/effects')

    def post_step(self, workflow, step, attempt, epoch, key):
        self.post_calls += 1
        body = dict(op=f'{workflow}:{step}', step=step, attempt=attempt,
                    permit_epoch=epoch, intent=INTENT[step])
        return self.request('POST', f'/w/{workflow}/{step}', body, key, POST_TIMEOUT)

    def stop(self):
        return self.request('POST', '/control/stop', {})


def plain_step(client, workflow, step, policy):
    key = f'{workflow}/{step}'
    permit = client.permit(workflow).get('body', {})
    epoch = int(permit.get('epoch', 1))
    events = []
    attempt = 1
    response = client.post_step(workflow, step, attempt, epoch, key)
    if response['ok'] and response['body'].get('state') == 'committed':
        return dict(ok=True, reason='committed', events=events)
    events.append(dict(action='post', attempt=attempt, ok=response['ok'],
                       error=response.get('error')))
    if policy == 'pause':
        return dict(ok=False, reason='single_pause', events=events)
    for _ in range(2):
        if policy == 'query_retry':
            observed = client.effects(workflow, step)
            body = observed.get('body') or {}
            events.append(dict(action='query', ok=observed['ok'], state=body.get('state')))
            if observed['ok'] and body.get('state') == 'committed':
                return dict(ok=True, reason='query_receipt', events=events)
            if (not observed['ok'] or body.get('complete') is not True
                    or body.get('state') != 'not_committed'):
                return dict(ok=False, reason='query_unknown', events=events)
        if policy == 'reauth_retry':
            client.reauthorize(workflow)
            epoch = int(client.permit(workflow).get('body', {}).get('epoch', epoch))
            events.append(dict(action='reauthorize', epoch=epoch))
        attempt += 1
        response = client.post_step(workflow, step, attempt, epoch, key)
        body = response.get('body') or {}
        events.append(dict(action='retry', attempt=attempt, ok=response['ok'],
                           state=body.get('state'), error=response.get('error')))
        if response['ok'] and body.get('state') == 'committed':
            return dict(ok=True, reason='retry_committed', events=events)
    return dict(ok=False, reason='retry_unconfirmed', events=events)


def clear_step(client, workflow, step, decisions):
    """CLEAR: lifecycle evidence for recovery, effect index only when asked."""
    op = f'{workflow}:{step}'
    permit = client.permit(workflow).get('body', {})
    if permit.get('allowed') is not True:
        return dict(ok=False, reason='permit_revoked_before_step', events=[])
    epoch = int(permit.get('epoch', 1))
    manifest = client.manifest()
    origin = dict(context=dict(operation_id=op, intent=INTENT[step], generation=1),
                  namespace='effects', manifest=manifest)
    qualification = inspect(origin, manifest, route_of(permit))
    if not qualification['valid']:
        return dict(ok=False, reason='destination_not_qualified', events=[])
    response = client.post_step(workflow, step, 1, epoch, f'{workflow}/{step}')
    if response['ok'] and positive(response['body'], origin):
        decisions.append(dict(step=step, action='complete', reason='original_receipt'))
        return dict(ok=True, reason='original_receipt', events=[])
    events = []
    attempt = 1
    for _ in range(8):
        current = client.manifest()
        verdict = decide(origin, current, CAPABILITIES, qualification, events, 4)
        decisions.append(dict(step=step, action=verdict['action'], reason=verdict['reason']))
        action = verdict['action']
        if action == 'complete':
            return dict(ok=True, reason=verdict['reason'], events=events)
        if action == 'pause':
            return dict(ok=False, reason=verdict['reason'], events=events)
        if action == 'wait':
            observed = client.lifecycle(workflow, step)
            body = dict(observed.get('body') or {})
            if observed['ok']:
                body['launch_manifest'] = digest(origin['manifest'])
                body.setdefault('effect_namespace', 'effects')
            events.append(dict(seq=len(events), context=dict(origin['context']),
                               action=action, body=body))
        elif action == 'query':
            observed = client.effects(workflow, step)
            body = dict(observed.get('body') or {})
            events.append(dict(seq=len(events), context=dict(origin['context']),
                               action=action, body=body))
        elif action == 'qualify':
            fresh = client.permit(workflow).get('body', {})
            qualification = inspect(origin, current, route_of(fresh))
            events.append(dict(seq=len(events), context=dict(origin['context']),
                               action='qualify', body=qualification))
        else:
            fresh = client.permit(workflow).get('body', {})
            if fresh.get('allowed') is not True:
                return dict(ok=False, reason='permit_revoked_before_retry', events=events)
            attempt += 1
            response = client.post_step(workflow, step, attempt,
                                        int(fresh.get('epoch', 1)), f'{workflow}/{step}')
            body = dict(response.get('body') or {})
            if response['ok'] and body.get('state') == 'committed':
                body['state'] = 'accepted'
            events.append(dict(seq=len(events), context=dict(origin['context']),
                               action='retry', body=body))
    return dict(ok=False, reason='budget_exhausted', events=events)


def run_workflow(client, workflow, policy, fault, seed):
    rng = random.Random((seed + 1) * 1000033 + FAULTS.index(fault) * 7919)
    decisions, records = [], []
    terminal, reason, stopped = 'complete', 'workflow_complete', None
    post_base, http_base = client.post_calls, client.http_calls
    begin = time.perf_counter_ns()
    for step in STEPS:
        time.sleep(rng.uniform(0.0, JITTER))
        if policy == 'clear':
            result = clear_step(client, workflow, step, decisions)
        else:
            result = plain_step(client, workflow, step, policy)
        records.append(dict(step=step, ok=result['ok'], reason=result['reason'],
                            events=result['events']))
        if not result['ok']:
            terminal, reason, stopped = 'paused', result['reason'], step
            break
    elapsed_ns = time.perf_counter_ns() - begin
    observed = client.state(workflow).get('body', {}).get('steps', {})
    rows = {step: int(observed.get(step, {}).get('rows', 0)) for step in STEPS}
    stale = {step: int(observed.get(step, {}).get('stale', 0)) for step in STEPS}
    completed = terminal == 'complete' and all(rows[step] >= 1 for step in STEPS)
    duplicates = sum(max(0, rows[step] - 1) for step in STEPS)
    stale_rows = sum(stale.values())
    safe = (completed and duplicates == 0 and stale_rows == 0
            and all(rows[step] == 1 for step in STEPS))
    return dict(workflow=workflow, fault=fault, policy=policy, seed=seed,
                terminal=terminal, reason=reason, stopped_at=stopped,
                completed=completed, safe=safe, duplicates=duplicates,
                stale_rows=stale_rows, orphan=int(not completed and rows['reserve'] >= 1),
                rows=rows, stale=stale, post_calls=client.post_calls - post_base,
                http_calls=client.http_calls - http_base, elapsed_ns=elapsed_ns,
                records=records, decisions=decisions)
