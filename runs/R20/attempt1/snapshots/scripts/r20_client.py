"""R20 controller: reuses the R19 step policies, with seed-chosen fault placements."""
import random
import time

import r19_client as base

STEPS = base.STEPS
POLICIES = base.POLICIES


def run_workflow(client, workflow, policy, placements, seed):
    rng = random.Random((seed + 1) * 1000033 + 31)
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
    return dict(workflow=workflow, policy=policy, seed=seed, placements=placements,
                terminal=terminal, reason=reason, stopped_at=stopped,
                completed=completed, false_complete=terminal == 'complete' and not completed,
                safe=safe, duplicates=duplicates, stale_rows=stale_rows,
                orphan=int(not completed and rows['reserve'] >= 1),
                rows=rows, stale=stale, post_calls=client.post_calls - post_base,
                http_calls=client.http_calls - http_base, elapsed_ns=elapsed_ns,
                records=records, decisions=decisions)
