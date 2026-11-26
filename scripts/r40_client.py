"""R40 client: explicit operation ids and intents (intent is part of the binding)."""
import json
from urllib.parse import urlsplit

import http.client

POST_TIMEOUT = 0.4
GET_TIMEOUT = 0.5


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

    def fence(self, workflow, op):
        response = self.request('POST', f'/w/{workflow}/fence', dict(op=op))
        if not response['ok']:
            return None
        return int(response['body'].get('fence', 0))

    def write(self, workflow, op, step, attempt, epoch, intent, fence, mode):
        body = dict(op=op, step=step, attempt=attempt, permit_epoch=epoch,
                    intent=intent, fence=fence, mode=mode)
        return self.request('POST', f'/w/{workflow}/write', body, POST_TIMEOUT)

    def finalize(self, workflow, op, fence):
        return self.request('POST', f'/w/{workflow}/finalize', dict(op=op, fence=fence))

    def legacy(self, workflow, step, attempt, epoch, intent, timeout=POST_TIMEOUT):
        body = dict(op=intent['op'], step=step, attempt=attempt, permit_epoch=epoch,
                    intent=intent['value'])
        return self.request('POST', f'/w/{workflow}/{step}', body, timeout)

    def effects(self, workflow, op):
        return self.request('GET', f'/w/{workflow}/ops/{op}/effects')

    def state(self, workflow):
        return self.request('GET', f'/w/{workflow}/state').get('body', {}).get('steps', {})

    def stop(self):
        return self.request('POST', '/control/stop', {})
