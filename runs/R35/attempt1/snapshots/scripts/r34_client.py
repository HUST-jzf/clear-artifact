"""R34 controller: two recoveries of one binding, three coordination mechanisms."""
import json
import threading
import time
from urllib.parse import urlsplit

import http.client

from clear_assurance.core import decide, digest, inspect, positive

STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
INTENT = {step: 'ticket:' + step for step in STEPS}
CAPABILITIES = dict(executor_handle=True, closed_registration=True)
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

    def lifecycle(self, workflow, step):
        return self.request('GET', f'/w/{workflow}/ops/{workflow}:{step}')

    def effects(self, workflow, step):
        return self.request('GET', f'/w/{workflow}/ops/{workflow}:{step}/effects')

    def append(self, workflow, step, attempt, epoch):
        body = dict(op=f'{workflow}:{step}', step=step, attempt=attempt,
                    permit_epoch=epoch, intent=INTENT[step])
        return self.request('POST', f'/w/{workflow}/{step}', body, POST_TIMEOUT)

    def admit(self, workflow, step, attempt, epoch):
        body = dict(op=f'{workflow}:{step}', step=step, attempt=attempt,
                    permit_epoch=epoch, intent=INTENT[step])
        return self.request('POST', f'/w/{workflow}/admit', body, POST_TIMEOUT)

    def lease(self, workflow, owner):
        return self.request('POST', f'/w/{workflow}/lease', dict(owner=owner))

    def state(self, workflow):
        return self.request('GET', f'/w/{workflow}/state').get('body', {}).get('steps', {})

    def stop(self):
        return self.request('POST', '/control/stop', {})


def wait_at(barrier):
    try:
        barrier.wait(timeout=2.0)
    except threading.BrokenBarrierError:
        pass


def recover(client, workflow, step, mechanism, owner, barrier):
    permit = client.permit(workflow)
    manifest = client.manifest()
    origin = dict(context=dict(operation_id=f'{workflow}:{step}', intent=INTENT[step],
                               generation=1),
                  namespace='effects', manifest=manifest)
    qualification = inspect(origin, manifest, route_of(permit))
    events, writes = [], 0
    for _ in range(10):
        current = client.manifest()
        verdict = decide(origin, current, CAPABILITIES, qualification, events, 4)
        action, reason = verdict['action'], verdict['reason']
        if action in ('complete', 'pause'):
            return dict(owner=owner, terminal=action, reason=reason, events=events,
                        writes=writes)
        if action == 'wait':
            response = client.lifecycle(workflow, step)
            body = dict(response.get('body') or {})
            if response['ok']:
                body['launch_manifest'] = digest(origin['manifest'])
                body.setdefault('effect_namespace', 'effects')
            events.append(dict(seq=len(events), context=dict(origin['context']),
                               action='wait', body=body))
        elif action == 'query':
            response = client.effects(workflow, step)
            events.append(dict(seq=len(events), context=dict(origin['context']),
                               action='query', body=dict(response.get('body') or {})))
        elif action == 'qualify':
            qualification = inspect(origin, current, route_of(client.permit(workflow)))
            events.append(dict(seq=len(events), context=dict(origin['context']),
                               action='qualify', body=qualification))
        else:
            wait_at(barrier)
            epoch = int(client.permit(workflow).get('epoch', 1))
            if mechanism == 'none':
                response = client.append(workflow, step, 2 + writes, epoch)
                writes += 1
                body = dict(response.get('body') or {})
                if response['ok'] and body.get('state') == 'committed':
                    body['state'] = 'accepted'
                events.append(dict(seq=len(events), context=dict(origin['context']),
                                   action='retry', body=body))
            elif mechanism == 'unique':
                response = client.admit(workflow, step, 2 + writes, epoch)
                if response['ok']:
                    writes += 1
                    body = dict(response['body'])
                    body['state'] = 'accepted'
                    events.append(dict(seq=len(events), context=dict(origin['context']),
                                       action='retry', body=body))
                elif response['body'].get('state') == 'duplicate_effect':
                    observed = client.effects(workflow, step)
                    events.append(dict(seq=len(events), context=dict(origin['context']),
                                       action='query', body=dict(observed.get('body') or {})))
                else:
                    events.append(dict(seq=len(events), context=dict(origin['context']),
                                       action='retry',
                                       body=dict(response.get('body') or {})))
            else:
                granted = client.lease(workflow, owner)
                if granted['ok']:
                    response = client.append(workflow, step, 2 + writes, epoch)
                    writes += 1
                    body = dict(response.get('body') or {})
                    if response['ok'] and body.get('state') == 'committed':
                        body['state'] = 'accepted'
                    events.append(dict(seq=len(events), context=dict(origin['context']),
                                       action='retry', body=body))
                else:
                    for _ in range(120):
                        observed = client.effects(workflow, step)
                        body = dict(observed.get('body') or {})
                        if body.get('state') == 'committed':
                            events.append(dict(seq=len(events),
                                               context=dict(origin['context']),
                                               action='query', body=body))
                            break
                        time.sleep(0.005)
                    else:
                        return dict(owner=owner, terminal='pause', reason='lease_denied',
                                    events=events, writes=writes)
    return dict(owner=owner, terminal='pause', reason='budget_exhausted', events=events,
                writes=writes)


def plain_post(client, workflow, step, attempt=1):
    epoch = int(client.permit(workflow).get('epoch', 1))
    return client.append(workflow, step, attempt, epoch)
