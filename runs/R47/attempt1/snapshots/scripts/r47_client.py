"""R47 client: seat effects, compensation and ownership transfer."""
import http.client
import json
from urllib.parse import urlsplit

POST_TIMEOUT = 0.3
GET_TIMEOUT = 0.6


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

    def write(self, workflow, op, intent, seat, epoch=1, fault_key=''):
        body = dict(op=op, intent=intent, seat=seat, epoch=epoch, fault_key=fault_key)
        return self.request('POST', f'/w/{workflow}/write', body, POST_TIMEOUT)

    def compensate(self, workflow, op, intent, fault_key='dispose'):
        body = dict(op=op, intent=intent, fault_key=fault_key)
        return self.request('POST', f'/w/{workflow}/compensate', body, POST_TIMEOUT)

    def transfer(self, workflow, from_op, from_intent, to_op, to_intent, seat,
                 fault_key='dispose'):
        body = dict(from_op=from_op, from_intent=from_intent, to_op=to_op,
                    to_intent=to_intent, seat=seat, fault_key=fault_key)
        return self.request('POST', f'/w/{workflow}/transfer', body, POST_TIMEOUT)

    def effects(self, workflow, op):
        return self.request('GET', f'/w/{workflow}/ops/{op}/effects')

    def active(self, workflow, op):
        body = self.effects(workflow, op).get('body') or {}
        return [row for row in body.get('effects') or []
                if row.get('kind') == 'effect' and row.get('state') == 'active']

    def stop(self):
        return self.request('POST', '/control/stop', {})
