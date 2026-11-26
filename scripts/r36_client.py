"""R36 controllers: evidence-only, fence settlement, and frontier gate."""
import time

import r38_client

Client = r38_client.Client
STEPS = r38_client.STEPS
INTENT = r38_client.INTENT


class GateClient(Client):
    def capabilities(self):
        return self.request('GET', '/capabilities').get('body', {})

    def buffer(self, workflow, step, attempt, seq):
        body = dict(op=f'{workflow}:{step}', step=step, attempt=attempt,
                    intent=INTENT[step], seq=seq)
        return self.request('POST', f'/w/{workflow}/buffer', body, 0.4)

    def gate(self, workflow, op, seq, action='commit'):
        return self.request('POST', f'/w/{workflow}/gate/{action}',
                            dict(op=op, seq=seq))


def frontier(client, workflow, step):
    op = f'{workflow}:{step}'
    epoch = int(client.permit(workflow).get('epoch', 1))
    caps = client.capabilities()
    if not caps.get('buffered'):
        response = client.legacy(workflow, step, 1, epoch)
        if response['ok']:
            return dict(terminal='complete', reason='initial_committed', writes=1,
                        buffered=False)
        return dict(terminal='pause', reason='buffer_unavailable', writes=1,
                    buffered=False)
    first = client.buffer(workflow, step, 1, 1)
    if first['ok']:
        settled = client.gate(workflow, op, 1)
        if settled['ok']:
            return dict(terminal='complete', reason='gate_committed', writes=1,
                        buffered=True)
        client.gate(workflow, op, 1, 'abort')
        return dict(terminal='pause', reason=settled['body'].get('state', 'gate_failed'),
                    writes=1, buffered=True)
    client.gate(workflow, op, 1, 'abort')
    second = client.buffer(workflow, step, 2, 2)
    if not second['ok']:
        return dict(terminal='pause', reason=second['body'].get('state', 'buffer_failed'),
                    writes=1, buffered=True)
    settled = client.gate(workflow, op, 2)
    if settled['ok']:
        return dict(terminal='complete', reason='frontier_committed', writes=2,
                    buffered=True)
    client.gate(workflow, op, 2, 'abort')
    return dict(terminal='pause', reason=settled['body'].get('state', 'gate_failed'),
                writes=1, buffered=True)


def clear_fenced(client, workflow, step):
    return r38_client.fenced(client, workflow, step)


def clear(client, workflow, step):
    return r38_client.clear(client, workflow, step)


def blind_retry(client, workflow, step):
    return r38_client.blind_retry(client, workflow, step)


POLICIES = dict(clear=clear, clear_fenced=clear_fenced, frontier=frontier,
                blind_retry=blind_retry)
