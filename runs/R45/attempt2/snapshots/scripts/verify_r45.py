"""R45 verifier: rebuild every cell from the workflow SQLite files and check
the pre-registered frontier (protocol sections 6, 10 and 11).

Recorded metrics are never trusted: committed rows, stale rows, provisional
rows, duplicates and rejections are read again from each workflow's database,
compared with `completion.json`, and only then aggregated.
"""
import argparse
import json
import sqlite3
import statistics
from pathlib import Path

STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
FAULTS = ['lost_return', 'late_commit', 'lost_before_commit', 'revoke']
CLEAR_POLICY = {'C0': 'clear_pause'}

EXPECT = {
    ('C0', 'clear_pause'): dict(lost_return='safe_pause', late_commit='safe_pause',
                                lost_before_commit='safe_pause', revoke='unsafe'),
    ('C0', 'timeout_retry'): dict(lost_return='unsafe', late_commit='unsafe',
                                  lost_before_commit='safe_complete', revoke='unsafe'),
    ('C1', 'clear_closure'): dict(lost_return='safe_complete', late_commit='unsafe',
                                  lost_before_commit='safe_pause', revoke='unsafe'),
    ('C2', 'verify_retry'): dict(lost_return='safe_complete', late_commit='unsafe',
                                 lost_before_commit='safe_complete', revoke='unsafe'),
    ('C2s', 'verify_retry'): dict(lost_return='unsafe', late_commit='unsafe',
                                  lost_before_commit='safe_complete', revoke='unsafe'),
    ('C3', 'clear_evidence'): dict(lost_return='safe_complete', late_commit='unsafe',
                                   lost_before_commit='safe_pause', revoke='unsafe'),
    ('C3s', 'clear_evidence'): dict(lost_return='safe_complete', late_commit='unsafe',
                                    lost_before_commit='safe_pause', revoke='unsafe'),
    ('C4', 'clear_evidence'): dict(lost_return='safe_complete', late_commit='safe_complete',
                                   lost_before_commit='safe_pause', revoke='safe_pause'),
    ('C4', 'verify_retry'): dict(lost_return='safe_complete', late_commit='unsafe',
                                 lost_before_commit='safe_complete', revoke='safe_pause'),
    ('C4', 'timeout_retry'): dict(lost_return='unsafe', late_commit='unsafe',
                                  lost_before_commit='safe_complete', revoke='safe_pause'),
    ('C5', 'clear_fenced'): dict(lost_return='safe_pause', late_commit='safe_complete',
                                 lost_before_commit='safe_complete', revoke='safe_pause'),
    ('C5', 'timeout_retry'): dict(lost_return='unsafe', late_commit='unsafe',
                                  lost_before_commit='safe_complete', revoke='safe_pause'),
    ('C6', 'clear_evidence'): dict(lost_return='safe_complete', late_commit='safe_complete',
                                   lost_before_commit='safe_pause', revoke='safe_pause'),
    ('C6', 'clear_fenced'): dict(lost_return='safe_complete', late_commit='safe_complete',
                                 lost_before_commit='safe_complete', revoke='safe_pause'),
    ('C6', 'timeout_retry'): dict(lost_return='unsafe', late_commit='unsafe',
                                  lost_before_commit='safe_complete', revoke='safe_pause'),
    ('C7', 'dedup_versioned'): dict(lost_return='safe_complete', late_commit='safe_complete',
                                    lost_before_commit='safe_complete', revoke='safe_pause'),
    ('C7', 'timeout_retry'): dict(lost_return='unsafe', late_commit='unsafe',
                                  lost_before_commit='safe_complete', revoke='safe_pause'),
}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def observe(path):
    db = sqlite3.connect(path)
    try:
        committed = {step: dict(rows=count, stale=stale) for step, count, stale in
                     db.execute("select step, count(*), "
                                "sum(case when allowed=0 then 1 else 0 end) "
                                "from effects where status='committed' group by step")}
        provisional = {step: count for step, count in
                       db.execute("select step, count(*) from effects "
                                  "where status='provisional' group by step")}
        hits = {step: count for step, count in
                db.execute('select step, count(*) from dedup_hits group by step')}
        rejected = db.execute('select count(*) from rejects').fetchone()[0]
    finally:
        db.close()
    rows = {step: int(committed.get(step, {}).get('rows', 0)) for step in STEPS}
    stale = sum(int(committed.get(step, {}).get('stale', 0)) for step in STEPS)
    return dict(rows=rows, stale=stale,
                provisional=sum(int(provisional.get(step, 0)) for step in STEPS),
                duplicates=sum(max(0, rows[step] - 1) for step in STEPS),
                deduplicated=sum(int(hits.get(step, 0)) for step in STEPS),
                rejected=int(rejected))


def classify(task, metric):
    if metric['duplicates'] > 0 or metric['stale'] > 0:
        return 'unsafe'
    if task['terminal'] == 'complete':
        if not all(metric['rows'][step] >= 1 for step in STEPS):
            return 'unsafe'
        return 'safe_complete'
    return 'safe_pause'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--out')
    args = parser.parse_args()
    run = Path(args.run)
    freeze = load(run / 'freeze.json')
    completion = load(run / 'completion.json')
    seeds = set(freeze['seeds'])
    policies = freeze['profile_policies']
    tasks = completion['tasks']
    checks, passed, mismatches = [], [], []

    def check(name, actual, expected):
        checks.append(name)
        if actual == expected:
            passed.append(name)
        else:
            print(json.dumps({'check': name, 'actual': actual, 'expected': expected}))

    check('meta.failures', completion['failures'], [])
    expected_tasks = sum(len(policies[p]) * len(FAULTS) * len(seeds) for p in policies)
    check('meta.tasks', len(tasks), expected_tasks)

    metrics = {}
    for task in tasks:
        path = run / task['profile'] / 'private' / (task['workflow'] + '.sqlite')
        metric = observe(path)
        metrics[task['workflow']] = metric
        if metric['rows'] != task['rows'] or metric['stale'] != task['stale'] \
                or metric['provisional'] != task['provisional'] \
                or metric['duplicates'] != task['duplicates'] \
                or metric['rejected'] != task['rejected']:
            mismatches.append(dict(workflow=task['workflow'],
                                   recorded=dict(rows=task['rows'], stale=task['stale'],
                                                 provisional=task['provisional'],
                                                 duplicates=task['duplicates'],
                                                 rejected=task['rejected']),
                                   observed=metric))
    check('sqlite.recompute-mismatches', mismatches, [])

    cells = {}
    for task in tasks:
        key = (task['profile'], task['policy'], task['fault'])
        metric = metrics[task['workflow']]
        cells.setdefault(key, []).append(dict(
            seed=task['seed'], terminal=task['terminal'],
            klass=classify(task, metric), requests=task['requests'],
            bytes=task['bytes'], elapsed_ns=task['elapsed_ns'],
            rows=metric['rows'], stale=metric['stale'],
            provisional=metric['provisional'], duplicates=metric['duplicates']))

    for profile, cell_policies in policies.items():
        for policy in cell_policies:
            for fault in FAULTS:
                key = (profile, policy, fault)
                rows = cells.get(key, [])
                check(f'count.{profile}.{policy}.{fault}', len(rows), len(seeds))
                classes = sorted({row['klass'] for row in rows})
                check(f'class-homogeneous.{profile}.{policy}.{fault}', len(classes), 1)

    for (profile, policy), expected in EXPECT.items():
        for fault, klass in expected.items():
            rows = cells.get((profile, policy, fault), [])
            actual = sorted({row['klass'] for row in rows})
            check(f'frontier.{profile}.{policy}.{fault}', actual, [klass])

    # C0's CLEAR: a pause in every grid cell, and no blind strategy is both
    # safe and complete outside the benign `lost_before_commit` case.
    pause = [row for row in cells[('C0', CLEAR_POLICY['C0'], 'lost_return')]
             + cells[('C0', 'clear_pause', 'late_commit')]
             + cells[('C0', 'clear_pause', 'lost_before_commit')]
             + cells[('C0', 'clear_pause', 'revoke')]]
    check('c0.clear-pause-rate', sum(1 for row in pause if row['terminal'] == 'pause'),
          len(pause))
    check('c0.no-safe-complete', sorted({row['klass'] for row in pause}),
          ['safe_pause', 'unsafe'])

    # Only profiles that can bind the write to the current qualification close
    # the revoke race without a residual effect.
    revoke_stale = {
        (profile, policy): sum(row['stale'] for row in cells[(profile, policy, 'revoke')])
        for profile, cell_policies in policies.items() for policy in cell_policies}
    for profile in ('C4', 'C5', 'C6', 'C7'):
        for policy in policies[profile]:
            check(f'revoke.no-residual.{profile}.{policy}',
                  revoke_stale[(profile, policy)], 0)
    for profile in ('C0', 'C1', 'C2', 'C2s', 'C3', 'C3s'):
        for policy in policies[profile]:
            check(f'revoke.residual.{profile}.{policy}',
                  revoke_stale[(profile, policy)] > 0, True)

    def median(values):
        return statistics.median(values) if values else 0

    frontier = {}
    for profile, cell_policies in policies.items():
        for policy in cell_policies:
            row = dict(faults={})
            for fault in FAULTS:
                rows = cells[(profile, policy, fault)]
                row['faults'][fault] = dict(
                    klass=sorted({r['klass'] for r in rows}),
                    requests=median([r['requests'] for r in rows]),
                    bytes=median([r['bytes'] for r in rows]),
                    elapsed_ms=median([r['elapsed_ns'] / 1e6 for r in rows]))
            row['safe_everywhere'] = all(
                set(row['faults'][fault]['klass']) <= {'safe_complete', 'safe_pause'}
                for fault in FAULTS)
            row['complete_everywhere'] = all(
                row['faults'][fault]['klass'] == ['safe_complete'] for fault in FAULTS)
            frontier[f'{profile}/{policy}'] = row

    all_safe = sorted(name for name, row in frontier.items() if row['safe_everywhere'])
    check('frontier.safe-everywhere', all_safe,
          ['C4/clear_evidence', 'C5/clear_fenced', 'C6/clear_evidence',
           'C6/clear_fenced', 'C7/dedup_versioned'])
    check('frontier.no-tier0-2-safe-everywhere',
          sorted(name for name in all_safe if name.startswith(('C0', 'C1', 'C2', 'C3'))),
          [])

    summary = dict(checks=len(checks), passed=len(passed),
                   status='pass' if len(passed) == len(checks) else 'fail',
                   mismatches=len(mismatches), frontier=frontier,
                   safe_everywhere=all_safe)
    out = Path(args.out) if args.out else run / 'verification.json'
    out.write_text(json.dumps(dict(summary, failed=[c for c in checks if c not in passed]),
                              ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('status', 'checks', 'passed', 'mismatches')}))
    if summary['status'] != 'pass':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
