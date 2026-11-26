"""R24/R30 client: CLEAR with an operator repair, and two resume strategies.

`clear` is the current controller: a pause ends the workflow. `clear_replay`
repairs the condition and then replays the paused step, which is what an operator
would do if the pause were treated as a plain failure. `clear_resume` repairs and
first asks the lifecycle endpoint whether the paused step already has a receipt
bound to it; only if it does not does it write again.

The difference between the two resume strategies is the whole point of R24.
"""
import random
import time

import r19_client as base

STEPS = base.STEPS
CLEAR_POLICIES = ['clear', 'clear_replay', 'clear_resume']


class Client(base.Client):
    def repair(self, workflow):
        return self.request('POST', f'/w/{workflow}/repair', {})


def receipt_present(client, workflow, step):
    observed = client.lifecycle(workflow, step)
    if not observed['ok']:
        return False
    body = observed.get('body') or {}
    receipt = body.get('receipt')
    return (body.get('terminal') is True and isinstance(receipt, dict)
            and receipt.get('operation_id') == f'{workflow}:{step}'
            and receipt.get('effect_namespace') == 'effects')


def run_workflow(client, workflow, policy, seed, condition):
    rng = random.Random((seed + 1) * 1000033 + (0 if 'revoke' in condition else 7919))
    decisions, records = [], []
    terminal, reason, stopped, repairs = 'complete', 'workflow_complete', None, 0
    post_base, http_base = client.post_calls, client.http_calls
    begin = time.perf_counter_ns()
    for step in STEPS:
        time.sleep(rng.uniform(0.0, base.JITTER))
        if policy in CLEAR_POLICIES:
            result = base.clear_step(client, workflow, step, decisions)
            if not result['ok'] and policy != 'clear':
                client.repair(workflow)
                repairs += 1
                if policy == 'clear_resume' and receipt_present(client, workflow, step):
                    result = dict(ok=True, reason='resumed_from_receipt', events=[])
                else:
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
    return dict(workflow=workflow, fault=condition, policy=policy, seed=seed,
                terminal=terminal, reason=reason, stopped_at=stopped,
                completed=completed, false_complete=terminal == 'complete' and not completed,
                safe=safe, duplicates=duplicates, stale_rows=stale_rows,
                orphan=int(not completed and rows['reserve'] >= 1),
                rows=rows, stale=stale, repairs=repairs,
                post_calls=client.post_calls - post_base,
                http_calls=client.http_calls - http_base, elapsed_ns=elapsed_ns,
                records=records, decisions=decisions)

