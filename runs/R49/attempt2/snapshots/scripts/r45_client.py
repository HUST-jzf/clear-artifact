"""R45 controllers: recovery policies conditioned on service capability.

A policy is only deployed on profiles that expose the endpoints it needs (see
`PROFILE_POLICIES` in `run_r45.py`), so a failing cell cannot be explained by
"the policy was not allowed to use a capability the service had".

Terminal states are `complete` and `pause`; `committed` records whether the
policy believes the step's effect is in place.
"""
import http.client
import json
from urllib.parse import urlsplit

STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
INTENT = {step: 'ticket:' + step for step in STEPS}
POST_TIMEOUT = 0.3
GET_TIMEOUT = 0.6
RETRY_BUDGET = 4


class Client:
    def __init__(self, base_url):
        parts = urlsplit(base_url)
        self.host, self.port = parts.hostname, parts.port
        self.calls = 0

    def request(self, method, path, body=None, timeout=GET_TIMEOUT):
        self.calls += 1
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

    def manifest(self, workflow):
        body = self.request('GET', f'/w/{workflow}/manifest').get('body', {})
        return dict(body.get('manifest') or {})

    def permit(self, workflow):
        return dict(self.request('GET', f'/permit/{workflow}').get('body') or {})

    def lifecycle(self, workflow, op):
        return self.request('GET', f'/w/{workflow}/ops/{op}')

    def effects(self, workflow, op):
        return self.request('GET', f'/w/{workflow}/ops/{op}/effects')

    def fence(self, workflow, op):
        return int(self.request('POST', f'/w/{workflow}/fence', dict(op=op))
                   .get('body', {}).get('fence', 0))

    def post_step(self, workflow, step, attempt, epoch, version):
        body = dict(op=f'{workflow}:{step}', step=step, attempt=attempt,
                    permit_epoch=epoch, manifest_version=version, intent=INTENT[step])
        return self.request('POST', f'/w/{workflow}/{step}', body, POST_TIMEOUT)

    def write(self, workflow, op, step, attempt, epoch, version, intent, fence, mode):
        body = dict(op=op, step=step, attempt=attempt, permit_epoch=epoch,
                    manifest_version=version, intent=intent, fence=fence, mode=mode)
        return self.request('POST', f'/w/{workflow}/write', body, POST_TIMEOUT)

    def admit(self, workflow, op, step, attempt, epoch, version, intent):
        body = dict(op=op, step=step, attempt=attempt, permit_epoch=epoch,
                    manifest_version=version, intent=intent)
        return self.request('POST', f'/w/{workflow}/admit', body, POST_TIMEOUT)

    def dedup(self, workflow, op, step, attempt, epoch, version, intent, key):
        body = dict(op=op, step=step, attempt=attempt, permit_epoch=epoch,
                    manifest_version=version, intent=intent, key=key)
        return self.request('POST', f'/w/{workflow}/dedup', body, POST_TIMEOUT)

    def finalize(self, workflow, op, fence):
        return self.request('POST', f'/w/{workflow}/finalize', dict(op=op, fence=fence))

    def state(self, workflow):
        return self.request('GET', f'/w/{workflow}/state')

    def stop(self):
        return self.request('POST', '/control/stop', {})


def positive(body):
    return body.get('state') == 'committed' and body.get('allowed') is True


def start(client, workflow, step):
    """Permit, manifest version and epoch a step's attempt is bound to."""
    permit = client.permit(workflow)
    version = client.manifest(workflow).get('version', '')
    return permit, int(permit.get('epoch', 1)), version


def clear_pause(client, workflow, step, axes):
    """Tier-0 CLEAR: one attempt, stop unless the receipt is positive."""
    permit, epoch, version = start(client, workflow, step)
    if permit.get('allowed') is not True:
        return dict(terminal='pause', reason='permit_revoked', committed=False)
    response = client.post_step(workflow, step, 1, epoch, version)
    if response['ok'] and positive(response['body']):
        return dict(terminal='complete', reason='initial_receipt', committed=True)
    return dict(terminal='pause', reason='no_evidence', committed=False)


def timeout_retry(client, workflow, step, axes):
    """Retry on timeout without reading any evidence."""
    permit, epoch, version = start(client, workflow, step)
    for attempt in range(1, RETRY_BUDGET + 1):
        response = client.post_step(workflow, step, attempt, epoch, version)
        if response['ok'] and positive(response['body']):
            return dict(terminal='complete', reason='retry_committed', committed=True)
    return dict(terminal='pause', reason='retry_unconfirmed', committed=False)


def clear_closure(client, workflow, step, axes):
    """Recovery driven by the execution lifecycle only."""
    op = f'{workflow}:{step}'
    permit, epoch, version = start(client, workflow, step)
    if permit.get('allowed') is not True:
        return dict(terminal='pause', reason='permit_revoked', committed=False)
    response = client.post_step(workflow, step, 1, epoch, version)
    if response['ok'] and positive(response['body']):
        return dict(terminal='complete', reason='initial_receipt', committed=True)
    for attempt in range(2, RETRY_BUDGET + 1):
        observed = client.lifecycle(workflow, op)
        if not observed['ok']:
            return dict(terminal='pause', reason='lifecycle_unavailable', committed=False)
        body = observed['body']
        receipt = body.get('receipt') or {}
        if body.get('state') == 'committed' and positive(receipt):
            return dict(terminal='complete', reason='lifecycle_receipt', committed=True)
        if body.get('state') == 'unknown' or body.get('terminal'):
            return dict(terminal='pause', reason='lifecycle_unknown', committed=False)
        response = client.post_step(workflow, step, attempt, epoch, version)
        if response['ok'] and positive(response['body']):
            return dict(terminal='complete', reason='retry_committed', committed=True)
    return dict(terminal='pause', reason='budget_exhausted', committed=False)


def verify_retry(client, workflow, step, axes):
    """Query the effect index, retry while it says `not_committed`."""
    op = f'{workflow}:{step}'
    permit, epoch, version = start(client, workflow, step)
    if permit.get('allowed') is not True:
        return dict(terminal='pause', reason='permit_revoked', committed=False)
    response = client.post_step(workflow, step, 1, epoch, version)
    if response['ok'] and positive(response['body']):
        return dict(terminal='complete', reason='initial_receipt', committed=True)
    for attempt in range(2, RETRY_BUDGET + 1):
        observed = client.effects(workflow, op)
        if not observed['ok']:
            return dict(terminal='pause', reason='effect_index_unavailable', committed=False)
        body = observed['body']
        if body.get('state') == 'committed':
            return dict(terminal='complete', reason='effect_index_committed', committed=True)
        if body.get('complete') is not True:
            return dict(terminal='pause', reason='effect_index_unknown', committed=False)
        response = client.post_step(workflow, step, attempt, epoch, version)
        if response['ok'] and positive(response['body']):
            return dict(terminal='complete', reason='retry_committed', committed=True)
    return dict(terminal='pause', reason='budget_exhausted', committed=False)


def clear_evidence(client, workflow, step, axes):
    """CLEAR: use every capability the profile exposes before retrying."""
    op = f'{workflow}:{step}'
    permit, epoch, version = start(client, workflow, step)
    intent = INTENT[step]
    if permit.get('allowed') is not True:
        return dict(terminal='pause', reason='permit_revoked', committed=False)
    if axes['staging']:
        fence = client.fence(workflow, op)
        response = client.write(workflow, op, step, 1, epoch, version, intent, fence,
                                'commit')
    elif axes['admission']:
        response = client.admit(workflow, op, step, 1, epoch, version, intent)
    else:
        response = client.post_step(workflow, step, 1, epoch, version)
    if response['ok'] and positive(response['body']):
        return dict(terminal='complete', reason='initial_receipt', committed=True)
    if response['ok'] and response['body'].get('state') == 'deduplicated':
        return dict(terminal='complete', reason='admission_existing', committed=True)
    if response['status'] == 403:
        return dict(terminal='pause', reason='stale_qualification', committed=False)
    for attempt in range(2, RETRY_BUDGET + 2):
        permit = client.permit(workflow)
        if permit.get('allowed') is not True:
            return dict(terminal='pause', reason='permit_revoked', committed=False)
        current = client.manifest(workflow)
        if axes['version'] and current.get('version') != version:
            return dict(terminal='pause', reason='manifest_changed', committed=False)
        if axes['closure']:
            observed = client.lifecycle(workflow, op)
            if observed['ok']:
                body = observed['body']
                receipt = body.get('receipt') or {}
                if body.get('state') == 'committed' and positive(receipt):
                    return dict(terminal='complete', reason='lifecycle_receipt',
                                committed=True)
                if body.get('state') == 'unknown':
                    return dict(terminal='pause', reason='lifecycle_unknown',
                                committed=False)
            elif observed['status'] is None or observed['status'] >= 500:
                return dict(terminal='pause', reason='lifecycle_unavailable',
                            committed=False)
        if axes['read'] != 'unavailable':
            observed = client.effects(workflow, op)
            if not observed['ok']:
                return dict(terminal='pause', reason='effect_index_unavailable',
                            committed=False)
            body = observed['body']
            rows = body.get('rows') or []
            if body.get('state') == 'committed':
                valid = [row for row in rows
                         if row.get('status') == 'committed' and row.get('allowed')]
                if valid:
                    return dict(terminal='complete', reason='effect_index_receipt',
                                committed=True)
                return dict(terminal='pause', reason='stale_effect_only', committed=False)
        if axes['staging']:
            fence = client.fence(workflow, op)
            staged = client.write(workflow, op, step, attempt, epoch, version, intent,
                                  fence, 'provisional')
            if not staged['ok']:
                if staged['status'] == 403:
                    return dict(terminal='pause', reason='stale_qualification',
                                committed=False)
                continue
            settled = client.finalize(workflow, op, fence)
            if settled['ok']:
                return dict(terminal='complete', reason='finalized', committed=True)
            if settled['body'].get('state') == 'already_committed':
                if axes['read'] != 'unavailable':
                    observed = client.effects(workflow, op)
                    rows = (observed.get('body') or {}).get('rows') or []
                    if any(row.get('status') == 'committed' and row.get('allowed')
                           for row in rows):
                        return dict(terminal='complete', reason='effect_index_receipt',
                                    committed=True)
                return dict(terminal='pause', reason='settled_elsewhere', committed=False)
            if settled['body'].get('state') == 'stale_fence':
                continue
            return dict(terminal='pause', reason='finalize_rejected', committed=False)
        elif axes['admission']:
            response = client.admit(workflow, op, step, attempt, epoch, version, intent)
            if response['status'] == 403:
                return dict(terminal='pause', reason='stale_qualification', committed=False)
            if response['ok'] and positive(response['body']):
                return dict(terminal='complete', reason='admission_committed',
                            committed=True)
        else:
            response = client.post_step(workflow, step, attempt, epoch, version)
            if response['ok'] and positive(response['body']):
                return dict(terminal='complete', reason='retry_committed', committed=True)
    return dict(terminal='pause', reason='budget_exhausted', committed=False)


def clear_fenced(client, workflow, step, axes):
    """Fence-ordered settlement without any effect read."""
    op = f'{workflow}:{step}'
    permit, epoch, version = start(client, workflow, step)
    intent = INTENT[step]
    if permit.get('allowed') is not True:
        return dict(terminal='pause', reason='permit_revoked', committed=False)
    fence = client.fence(workflow, op)
    response = client.write(workflow, op, step, 1, epoch, version, intent, fence, 'commit')
    if response['ok'] and positive(response['body']):
        return dict(terminal='complete', reason='initial_committed', committed=True)
    if response['status'] == 403:
        return dict(terminal='pause', reason='stale_qualification', committed=False)
    for attempt in range(2, RETRY_BUDGET + 1):
        permit = client.permit(workflow)
        if permit.get('allowed') is not True:
            return dict(terminal='pause', reason='permit_revoked', committed=False)
        fence = client.fence(workflow, op)
        staged = client.write(workflow, op, step, attempt, epoch, version, intent,
                              fence, 'provisional')
        if not staged['ok']:
            if staged['status'] == 403:
                return dict(terminal='pause', reason='stale_qualification',
                            committed=False)
            if staged['body'].get('state') == 'stale_fence':
                continue
            return dict(terminal='pause', reason='stage_rejected', committed=False)
        settled = client.finalize(workflow, op, fence)
        if settled['ok']:
            return dict(terminal='complete', reason='finalized', committed=True)
        if settled['body'].get('state') == 'already_committed':
            if axes['read'] != 'unavailable':
                observed = client.effects(workflow, op)
                rows = (observed.get('body') or {}).get('rows') or []
                if any(row.get('status') == 'committed' and row.get('allowed')
                       for row in rows):
                    return dict(terminal='complete', reason='effect_index_receipt',
                                committed=True)
            return dict(terminal='pause', reason='settled_elsewhere', committed=False)
        if settled['body'].get('state') == 'stale_fence':
            continue
        return dict(terminal='pause', reason='finalize_rejected', committed=False)
    return dict(terminal='pause', reason='budget_exhausted', committed=False)


def dedup_versioned(client, workflow, step, axes):
    """Traditional exactly-once: stable versioned key, atomic insert-or-return."""
    op = f'{workflow}:{step}'
    permit, epoch, version = start(client, workflow, step)
    intent = INTENT[step]
    key = f'{workflow}:{step}:{intent}:{version}'
    if permit.get('allowed') is not True:
        return dict(terminal='pause', reason='permit_revoked', committed=False)
    for attempt in range(1, RETRY_BUDGET + 1):
        response = client.dedup(workflow, op, step, attempt, epoch, version, intent, key)
        if response['ok']:
            state = response['body'].get('state')
            if state in ('committed', 'deduplicated'):
                return dict(terminal='complete', reason=state, committed=True)
        if response['status'] == 403:
            return dict(terminal='pause', reason='stale_qualification', committed=False)
    return dict(terminal='pause', reason='dedup_failed', committed=False)


POLICIES = dict(clear_pause=clear_pause, timeout_retry=timeout_retry,
                clear_closure=clear_closure, verify_retry=verify_retry,
                clear_evidence=clear_evidence, clear_fenced=clear_fenced,
                dedup_versioned=dedup_versioned)
