"""R25 client: the R19 controller driving a payment workflow.

`authorize -> capture -> settle -> notify`. Only `capture` carries an amount, and
`capture` rows are charges, so a duplicate capture is reported as a double charge
via the `/ledger` endpoint rather than as a row count.

`r19_client` keeps its step list and intent map at module level; this module
rebinds both at import time so the shared controller code drives the payment
steps unchanged.
"""
import random
import time

import r19_client as base

STEPS = ['authorize', 'capture', 'settle', 'notify']
INTENT = {step: 'payment:' + step for step in STEPS}
AMOUNT = {'authorize': 0, 'capture': 2500, 'settle': 0, 'notify': 0}
CHARGE = AMOUNT['capture']

base.STEPS = STEPS
base.INTENT = INTENT


class Client(base.Client):
    def post_step(self, workflow, step, attempt, epoch, key):
        self.post_calls += 1
        body = dict(op=f'{workflow}:{step}', step=step, attempt=attempt,
                    permit_epoch=epoch, intent=INTENT[step], amount=AMOUNT[step])
        return self.request('POST', f'/w/{workflow}/{step}', body, key,
                            base.POST_TIMEOUT)

    def ledger(self, workflow):
        return self.request('GET', f'/w/{workflow}/ledger')


def run_workflow(client, workflow, policy, fault, seed):
    """Same loop as `r19_client.run_workflow`, with a domain-neutral orphan flag."""
    rng = random.Random((seed + 1) * 1000033 + base.FAULTS.index(fault) * 7919)
    decisions, records = [], []
    terminal, reason, stopped = 'complete', 'workflow_complete', None
    post_base, http_base = client.post_calls, client.http_calls
    begin = time.perf_counter_ns()
    for step in STEPS:
        time.sleep(rng.uniform(0.0, base.JITTER))
        if policy == 'clear':
            result = base.clear_step(client, workflow, step, decisions)
        else:
            result = base.plain_step(client, workflow, step, policy)
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
                completed=completed, false_complete=terminal == 'complete' and not completed,
                safe=safe, duplicates=duplicates, stale_rows=stale_rows,
                orphan=int(not completed and any(rows[step] >= 1 for step in STEPS)),
                rows=rows, stale=stale, post_calls=client.post_calls - post_base,
                http_calls=client.http_calls - http_base, elapsed_ns=elapsed_ns,
                records=records, decisions=decisions)
