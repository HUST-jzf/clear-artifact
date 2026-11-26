"""R38 controllers: evidence-only CLEAR and fence-ordered settlement."""
import json
import time
from urllib.parse import urlsplit

import http.client

from clear_assurance.core import decide, digest, inspect, positive

STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
INTENT = {step: 'ticket:' + step for step in STEPS}
POST_TIMEOUT = 0.4
GET_TIMEOUT = 0.5


def route_of(permit):
    return dict(mode='inline', closed_registration=True,
                allowed=permit.get('allowed') is True, store='effects')


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

    def manifest(self):
        return self.request('GET', '/manifest').get('body', {}).get('manifest', {})

    def permit(self, workflow):
        return self.request('GET', f'/permit/{workflow}').get('body', {})

    def lifecycle(self, workflow, op):
        return self.request('GET', f'/w/{workflow}/ops/{op}')

    def effects(self, workflow, op):
        return self.request('GET', f'/w/{workflow}/ops/{op}/effects')

    def fence(self, workflow, op):
        return int(self.request('POST', f'/w/{workflow}/fence', dict(op=op))
                   .get('body', {}).get('fence', 0))

    def write(self, workflow, step, attempt, epoch, fence, mode):
        body = dict(op=f'{workflow}:{step}', step=step, attempt=attempt,
                    permit_epoch=epoch, intent=INTENT[step], fence=fence, mode=mode)
        return self.request('POST', f'/w/{workflow}/write', body, POST_TIMEOUT)

    def finalize(self, workflow, op, fence):
        return self.request('POST', f'/w/{workflow}/finalize', dict(op=op, fence=fence))

    def legacy(self, workflow, step, attempt, epoch):
        body = dict(op=f'{workflow}:{step}', step=step, attempt=attempt,
                    permit_epoch=epoch, intent=INTENT[step])
        return self.request('POST', f'/w/{workflow}/{step}', body, POST_TIMEOUT)

    def state(self, workflow):
        return self.request('GET', f'/w/{workflow}/state').get('body', {}).get('steps', {})

    def stop(self):
        return self.request('POST', '/control/stop', {})


def capabilities(client, workflow, op):
    response = client.lifecycle(workflow, op)
    if response['status'] == 501:
        return dict(executor_handle=False, closed_registration=False)
    return dict(executor_handle=True, closed_registration=True)


def observe_closed(client, workflow, op, timeout=2.5):
    deadline = time.monotonic() + timeout
    body = {}
    while time.monotonic() < deadline:
        response = client.lifecycle(workflow, op)
        body = dict(response.get('body') or {})
        if response['status'] == 501 or body.get('terminal'):
            return body
        time.sleep(0.02)
    return body


def clear(client, workflow, step):
    op = f'{workflow}:{step}'
    caps = capabilities(client, workflow, op)
    permit = client.permit(workflow)
    manifest = client.manifest()
    origin = dict(context=dict(operation_id=op, intent=INTENT[step], generation=1),
                  namespace='effects', manifest=manifest)
    qualification = inspect(origin, manifest, route_of(permit))
    events = []
    epoch = int(permit.get('epoch', 1))
    response = client.legacy(workflow, step, 1, epoch)
    if response['ok'] and response['body'].get('state') == 'committed':
        return dict(terminal='complete', reason='initial_committed', writes=1, events=events)
    for _ in range(10):
        current = client.manifest()
        verdict = decide(origin, current, caps, qualification, events, 4)
        action, reason = verdict['action'], verdict['reason']
        if action in ('complete', 'pause'):
            return dict(terminal=action, reason=reason, writes=len(events), events=events)
        if action == 'wait':
            body = observe_closed(client, workflow, op)
            if body:
                body['launch_manifest'] = digest(origin['manifest'])
                body.setdefault('effect_namespace', 'effects')
            events.append(dict(seq=len(events), context=dict(origin['context']),
                               action='wait', body=body))
        elif action == 'query':
            body = dict(client.effects(workflow, op).get('body') or {})
            events.append(dict(seq=len(events), context=dict(origin['context']),
                               action='query', body=body))
        elif action == 'qualify':
            qualification = inspect(origin, current, route_of(client.permit(workflow)))
            events.append(dict(seq=len(events), context=dict(origin['context']),
                               action='qualify', body=qualification))
        else:
            response = client.legacy(workflow, step, 2, epoch)
            body = dict(response.get('body') or {})
            if response['ok'] and body.get('state') == 'committed':
                body['state'] = 'accepted'
            events.append(dict(seq=len(events), context=dict(origin['context']),
                               action='retry', body=body))
    return dict(terminal='pause', reason='budget_exhausted', writes=len(events), events=events)


def fenced(client, workflow, step):
    op = f'{workflow}:{step}'
    epoch = int(client.permit(workflow).get('epoch', 1))
    fence = client.fence(workflow, op)
    response = client.write(workflow, step, 1, epoch, fence, 'commit')
    if response['ok'] and response['body'].get('state') == 'committed':
        return dict(terminal='complete', reason='initial_committed', writes=1,
                    fenced=True)
    body = dict(client.effects(workflow, op).get('body') or {})
    if body.get('state') == 'committed':
        return dict(terminal='complete', reason='observed_committed', writes=1,
                    fenced=True)
    fence = client.fence(workflow, op)
    staged = client.write(workflow, step, 2, epoch, fence, 'provisional')
    if not staged['ok']:
        if staged['body'].get('state') in ('stale_fence', 'duplicate_effect'):
            body = dict(client.effects(workflow, op).get('body') or {})
            if body.get('state') == 'committed':
                return dict(terminal='complete', reason='observed_committed',
                            writes=1, fenced=True)
        return dict(terminal='pause', reason=staged['body'].get('state', 'stage_failed'),
                    writes=1, fenced=True)
    settled = client.finalize(workflow, op, fence)
    if settled['ok']:
        return dict(terminal='complete', reason='finalized', writes=2, fenced=True)
    if settled['body'].get('state') == 'already_committed':
        body = dict(client.effects(workflow, op).get('body') or {})
        if body.get('state') == 'committed':
            return dict(terminal='complete', reason='observed_committed', writes=2,
                        fenced=True)
    return dict(terminal='pause', reason=settled['body'].get('state', 'finalize_failed'),
                writes=2, fenced=True)


def blind_retry(client, workflow, step):
    epoch = int(client.permit(workflow).get('epoch', 1))
    response = client.legacy(workflow, step, 1, epoch)
    if response['ok']:
        return dict(terminal='complete', reason='initial_committed', writes=1)
    retried = client.legacy(workflow, step, 2, epoch)
    if retried['ok']:
        return dict(terminal='complete', reason='retry_committed', writes=2)
    return dict(terminal='pause', reason='retry_failed', writes=1)


def pause(client, workflow, step):
    epoch = int(client.permit(workflow).get('epoch', 1))
    response = client.legacy(workflow, step, 1, epoch)
    if response['ok']:
        return dict(terminal='complete', reason='initial_committed', writes=1)
    return dict(terminal='pause', reason='no_retry', writes=0)


POLICIES = dict(clear=clear, clear_fenced=fenced, blind_retry=blind_retry, pause=pause)
