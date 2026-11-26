"""R44 controllers: fence settlement vs atomic key dedup, same retry budget."""
import json
from urllib.parse import urlsplit

import http.client

POST_TIMEOUT = 0.4
GET_TIMEOUT = 0.5


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

    def manifest(self):
        return self.request('GET', '/manifest').get('body', {}).get('manifest', {})

    def permit(self, workflow):
        return self.request('GET', f'/permit/{workflow}').get('body', {})

    def effects(self, workflow, op):
        return self.request('GET', f'/w/{workflow}/ops/{op}/effects')

    def fence(self, workflow, op):
        return int(self.request('POST', f'/w/{workflow}/fence', dict(op=op))
                   .get('body', {}).get('fence', 0))

    def write(self, workflow, op, step, attempt, epoch, intent, fence, mode):
        body = dict(op=op, step=step, attempt=attempt, permit_epoch=epoch,
                    intent=intent, fence=fence, mode=mode)
        return self.request('POST', f'/w/{workflow}/write', body, POST_TIMEOUT)

    def finalize(self, workflow, op, fence):
        return self.request('POST', f'/w/{workflow}/finalize', dict(op=op, fence=fence))

    def dedup(self, workflow, op, step, attempt, epoch, intent, key):
        body = dict(op=op, step=step, attempt=attempt, permit_epoch=epoch,
                    intent=intent, key=key)
        return self.request('POST', f'/w/{workflow}/dedup', body, POST_TIMEOUT)

    def stop(self):
        return self.request('POST', '/control/stop', {})


def _committed(client, workflow, op):
    body = dict(client.effects(workflow, op).get('body') or {})
    return body.get('state') == 'committed', body


def fenced(client, workflow, op, step, intent, attempt=1):
    """CLEAR L2': initial commit at the initial fence, recovery via provisional+finalize."""
    epoch = int(client.permit(workflow).get('epoch', 1))
    fence = client.fence(workflow, op)
    response = client.write(workflow, op, step, attempt, epoch, intent, fence, 'commit')
    if response['ok'] and response['body'].get('state') == 'committed':
        return dict(terminal='complete', reason='initial_committed', committed=True)
    committed, body = _committed(client, workflow, op)
    if committed:
        return dict(terminal='complete', reason='observed_committed', committed=True)
    fence = client.fence(workflow, op)
    staged = client.write(workflow, op, step, attempt + 1, epoch, intent, fence, 'provisional')
    if not staged['ok']:
        committed, body = _committed(client, workflow, op)
        if committed:
            return dict(terminal='complete', reason='observed_committed', committed=True)
        return dict(terminal='pause', reason=staged['body'].get('state', 'stage_failed'),
                    committed=False)
    settled = client.finalize(workflow, op, fence)
    if settled['ok']:
        return dict(terminal='complete', reason='finalized', committed=True)
    if settled['body'].get('state') == 'already_committed':
        committed, body = _committed(client, workflow, op)
        if committed:
            return dict(terminal='complete', reason='observed_committed', committed=True)
    return dict(terminal='pause', reason=settled['body'].get('state', 'finalize_failed'),
                committed=False)


def dedup(client, workflow, op, step, intent, key, fresh=False):
    """Atomic insert-or-return on `key`; one retry with the same key."""
    epoch = int(client.permit(workflow).get('epoch', 1))
    first = client.dedup(workflow, op, step, 1, epoch, intent, key)
    if first['ok']:
        return dict(terminal='complete', reason=first['body'].get('state', 'committed'),
                    committed=True)
    second_key = key + ':attempt2' if fresh else key
    second = client.dedup(workflow, op, step, 2, epoch, intent, second_key)
    if second['ok']:
        return dict(terminal='complete', reason=second['body'].get('state', 'committed'),
                    committed=True)
    return dict(terminal='pause', reason=second['body'].get('state', 'dedup_failed'),
                committed=False)
