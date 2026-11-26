"""R47 verifier: rebuild task-level metrics from each workflow's SQLite file."""
import argparse
import json
import sqlite3
from pathlib import Path

CASES = ['change_before_commit', 'change_after_commit', 'late_after_b']
DISPOSALS = ['none', 'compensate_after_commit', 'ownership_transfer', 'pause_escalate']


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def observe(path):
    db = sqlite3.connect(path)
    try:
        effects = [dict(op=row[0], intent=row[1], seat=row[2], kind=row[3],
                        state=row[4]) for row in
                   db.execute('select op, intent, seat, kind, state from effects '
                              'order by id')]
        mutations = db.execute('select count(*) from mutations').fetchone()[0]
    finally:
        db.close()
    return dict(effects=effects, mutations=int(mutations))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--out')
    args = parser.parse_args()
    run = Path(args.run)
    completion = load(run / 'completion.json')
    tasks = completion['tasks']
    checks, passed, mismatches = [], [], []

    def check(name, actual, expected):
        checks.append(name)
        if actual == expected:
            passed.append(name)
        else:
            print(json.dumps({'check': name, 'actual': actual, 'expected': expected}))

    check('meta.failures', completion['failures'], [])
    check('meta.tasks', len(tasks), 72)

    for task in tasks:
        metric = observe(run / 'private' / (task['workflow'] + '.sqlite'))
        if metric['effects'] != task['effects'] or metric['mutations'] != task['writes']:
            mismatches.append(dict(workflow=task['workflow'],
                                   recorded=dict(effects=task['effects'],
                                                 writes=task['writes']),
                                   observed=metric))
    check('sqlite.recompute-mismatches', mismatches, [])

    def select(case, disposal, normal=None):
        rows = [task for task in tasks
                if task['case'] == case and task['disposal'] == disposal]
        if normal is True:
            rows = [task for task in rows if task['run'] <= 3]
        elif normal is False:
            rows = [task for task in rows if task['run'] > 3]
        return rows

    for case in CASES:
        for disposal in DISPOSALS:
            check(f'count.{case}.{disposal}', len(select(case, disposal)), 6)

    for case in CASES:
        rows = select(case, 'none')
        check(f'none.residual.{case}', sorted({task['residual'] for task in rows}), [1])
        check(f'none.complete.{case}',
              sum(1 for task in rows if task['task_complete']), 0)

    for case in ('change_before_commit', 'change_after_commit'):
        rows = select(case, 'compensate_after_commit', normal=True)
        check(f'compensate.residual.{case}', sorted({task['residual'] for task in rows}),
              [0])
        check(f'compensate.complete.{case}',
              sum(1 for task in rows if task['task_complete']), 3)
        check(f'compensate.writes.{case}', sorted({task['writes'] for task in rows}), [3])
    rows = select('late_after_b', 'compensate_after_commit', normal=True)
    check('compensate.residual.late_after_b', sorted({task['residual'] for task in rows}),
          [1])
    check('compensate.complete.late_after_b',
          sum(1 for task in rows if task['task_complete']), 0)

    for case in CASES:
        rows = select(case, 'ownership_transfer', normal=True)
        check(f'transfer.residual.{case}', sorted({task['residual'] for task in rows}), [0])
        check(f'transfer.complete.{case}',
              sum(1 for task in rows if task['task_complete']), 3)
    for case in ('change_before_commit', 'change_after_commit'):
        rows = select(case, 'ownership_transfer', normal=True)
        check(f'transfer.writes.{case}', sorted({task['writes'] for task in rows}), [2])

    for disposal in ('compensate_after_commit', 'ownership_transfer'):
        for case in CASES:
            rows = select(case, disposal, normal=False)
            check(f'dispose-fault.residual.{disposal}.{case}',
                  sorted({task['residual'] for task in rows}), [1])
            check(f'dispose-fault.complete.{disposal}.{case}',
                  sum(1 for task in rows if task['task_complete']), 0)

    for case in ('change_before_commit', 'change_after_commit'):
        rows = select(case, 'pause_escalate')
        check(f'pause.escalated.{case}',
              sum(1 for task in rows if task['escalated']), 6)
        check(f'pause.complete.{case}',
              sum(1 for task in rows if task['task_complete']), 0)
    rows = select('late_after_b', 'pause_escalate')
    check('pause.escalated.late_after_b',
          sum(1 for task in rows if task['escalated']), 0)
    check('pause.residual.late_after_b', sorted({task['residual'] for task in rows}), [1])

    normal_totals = {
        disposal: sum(1 for case in CASES
                      for task in select(case, disposal, normal=True)
                      if task['task_complete'])
        for disposal in DISPOSALS}
    check('completion.normal.transfer', normal_totals['ownership_transfer'], 9)
    check('completion.normal.compensate', normal_totals['compensate_after_commit'], 6)
    check('completion.normal.none', normal_totals['none'], 0)
    check('completion.normal.pause', normal_totals['pause_escalate'], 0)

    table = {}
    for disposal in DISPOSALS:
        entry = {}
        for case in CASES:
            rows = select(case, disposal)
            entry[case] = dict(
                residual=sorted({task['residual'] for task in rows}),
                complete=sum(1 for task in rows if task['task_complete']),
                escalated=sum(1 for task in rows if task['escalated']),
                writes=sorted({task['writes'] for task in rows}))
        table[disposal] = entry

    summary = dict(checks=len(checks), passed=len(passed),
                   status='pass' if len(passed) == len(checks) else 'fail',
                   mismatches=len(mismatches), completion=normal_totals, table=table)
    out = Path(args.out) if args.out else run / 'verification.json'
    out.write_text(json.dumps(dict(summary, failed=[c for c in checks if c not in passed]),
                              ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('status', 'checks', 'passed', 'mismatches')}))
    if summary['status'] != 'pass':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
