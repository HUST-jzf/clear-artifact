"""R46 controllers: identity construction and recovery are separate steps.

Each policy exposes `initial` (the first call, which may hit the fault) and
`recover` (the second call after the controller observed an ambiguous outcome).
The identity a policy can construct depends on the regime:

    fixed   H(op, intent, version)
    fresh   H(op, intent, version, attempt)
    none    no key; the service dedups on the content hash of the arguments

`semantic_dedup` always sends the content hash as its key, which is what the
content regime uses internally.
"""
import hashlib
import http.client
import json
from urllib.parse import urlsplit

STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
POST_TIMEOUT = 0.3
GET_TIMEOUT = 0.6
RETRY_BUDGET = 3


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def content_key(args):
    return digest(json.dumps(args, sort_keys=True, separators=(',', ':')))


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
        return dict(self.request('GET', '/manifest').get('body', {}).get('manifest') or {})

    def permit(self, workflow):
        return dict(self.request('GET', f'/permit/{workflow}').get('body') or {})

    def lifecycle(self, workflow, op):
        return self.request('GET', f'/w/{workflow}/ops/{op}')

    def effects(self, workflow, op):
        return self.request('GET', f'/w/{workflow}/ops/{op}/effects')

    def fence(self, workflow, op):
        return int(self.request('POST', f'/w/{workflow}/fence', dict(op=op))
                   .get('body', {}).get('fence', 0))

    def admit(self, workflow, op, intent, args, attempt):
        body = dict(op=op, step='attach', attempt=attempt, intent=intent, args=args)
        return self.request('POST', f'/w/{workflow}/admit', body, POST_TIMEOUT)

    def dedup(self, workflow, op, intent, args, attempt, key):
        body = dict(op=op, step='attach', attempt=attempt, intent=intent, args=args,
                    key=key)
        return self.request('POST', f'/w/{workflow}/dedup', body, POST_TIMEOUT)

    def write(self, workflow, op, intent, args, attempt, fence, mode):
        body = dict(op=op, step='attach', attempt=attempt, intent=intent, args=args,
                    fence=fence, mode=mode)
        return self.request('POST', f'/w/{workflow}/write', body, POST_TIMEOUT)

    def finalize(self, workflow, op, fence):
        return self.request('POST', f'/w/{workflow}/finalize', dict(op=op, fence=fence))

    def stop(self):
        return self.request('POST', '/control/stop', {})


def ok(body):
    return body.get('state') in ('committed', 'deduplicated')


def dedup_with(client, workflow, op, intent, args, attempt, key):
    response = client.dedup(workflow, op, intent, args, attempt, key)
    if response['ok'] and ok(response['body']):
        return dict(terminal='complete', reason=response['body'].get('state'))
    return dict(terminal='pause', reason=response['body'].get('state', 'dedup_failed'))


def versioned_key(client, op, intent):
    return digest(f'{op}|{intent}|{client.manifest().get("version", "")}')


def fresh_key(client, op, intent, attempt):
    return digest(f'{op}|{intent}|{client.manifest().get("version", "")}|{attempt}')


def initial_versioned(client, workflow, op, intent, args, attempt):
    return dedup_with(client, workflow, op, intent, args, attempt,
                      versioned_key(client, op, intent))


def recover_versioned(client, workflow, op, intent, args, attempt):
    return dedup_with(client, workflow, op, intent, args, attempt,
                      versioned_key(client, op, intent))


def initial_fresh(client, workflow, op, intent, args, attempt):
    return dedup_with(client, workflow, op, intent, args, attempt,
                      fresh_key(client, op, intent, attempt))


def recover_fresh(client, workflow, op, intent, args, attempt):
    return dedup_with(client, workflow, op, intent, args, attempt,
                      fresh_key(client, op, intent, attempt))


def initial_semantic(client, workflow, op, intent, args, attempt):
    return dedup_with(client, workflow, op, intent, args, attempt, content_key(args))


def recover_semantic(client, workflow, op, intent, args, attempt):
    return dedup_with(client, workflow, op, intent, args, attempt, content_key(args))


def initial_write(client, workflow, op, intent, args, attempt):
    response = client.write(workflow, op, intent, args, attempt, None, 'commit')
    if response['ok'] and response['body'].get('state') == 'committed':
        return dict(terminal='complete', reason='committed')
    return dict(terminal='pause', reason=response['body'].get('state', 'write_failed'))


def recover_verify(client, workflow, op, intent, args, attempt):
    for round_ in range(RETRY_BUDGET):
        observed = client.effects(workflow, op)
        body = observed.get('body') or {}
        if observed['ok'] and body.get('state') == 'committed':
            return dict(terminal='complete', reason='effect_index_committed')
        response = client.write(workflow, op, intent, args, attempt + round_, None, 'commit')
        if response['ok'] and response['body'].get('state') == 'committed':
            return dict(terminal='complete', reason='retry_committed')
    return dict(terminal='pause', reason='retry_unconfirmed')


def initial_fenced(client, workflow, op, intent, args, attempt):
    fence = client.fence(workflow, op)
    response = client.write(workflow, op, intent, args, attempt, fence, 'commit')
    if response['ok'] and response['body'].get('state') == 'committed':
        return dict(terminal='complete', reason='committed')
    return dict(terminal='pause', reason=response['body'].get('state', 'write_failed'))


def recover_fenced(client, workflow, op, intent, args, attempt):
    fence = client.fence(workflow, op)
    staged = client.write(workflow, op, intent, args, attempt, fence, 'provisional')
    if not staged['ok']:
        return dict(terminal='pause', reason=staged['body'].get('state', 'stage_failed'))
    settled = client.finalize(workflow, op, fence)
    if settled['ok']:
        return dict(terminal='complete', reason='finalized')
    if settled['body'].get('state') == 'already_committed':
        observed = client.effects(workflow, op)
        body = observed.get('body') or {}
        if body.get('state') == 'committed':
            return dict(terminal='complete', reason='observed_committed')
    return dict(terminal='pause', reason=settled['body'].get('state', 'finalize_failed'))


def initial_admit(client, workflow, op, intent, args, attempt):
    response = client.admit(workflow, op, intent, args, attempt)
    if response['ok'] and response['body'].get('state') == 'committed':
        if response['body'].get('intent') == intent:
            return dict(terminal='complete', reason='admitted')
        return dict(terminal='pause', reason='intent_mismatch')
    return dict(terminal='pause', reason=response['body'].get('state', 'admit_failed'))


def recover_admit(client, workflow, op, intent, args, attempt):
    for round_ in range(RETRY_BUDGET):
        observed = client.lifecycle(workflow, op)
        if observed['ok']:
            body = observed['body']
            receipt = body.get('receipt') or {}
            if receipt:
                if receipt.get('intent') == intent:
                    return dict(terminal='complete', reason='bound_receipt')
                return dict(terminal='pause', reason='intent_mismatch')
        response = client.admit(workflow, op, intent, args, attempt + round_)
        if response['ok'] and response['body'].get('state') == 'committed':
            if response['body'].get('intent') == intent:
                return dict(terminal='complete', reason='admitted')
            return dict(terminal='pause', reason='intent_mismatch')
    return dict(terminal='pause', reason='budget_exhausted')


POLICIES = {
    'dedup_versioned': dict(initial=initial_versioned, recover=recover_versioned),
    'dedup_fresh': dict(initial=initial_fresh, recover=recover_fresh),
    'semantic_dedup': dict(initial=initial_semantic, recover=recover_semantic),
    'verify_retry': dict(initial=initial_write, recover=recover_verify),
    'clear_fenced': dict(initial=initial_fenced, recover=recover_fenced),
    'clear_evidence': dict(initial=initial_admit, recover=recover_admit),
}
