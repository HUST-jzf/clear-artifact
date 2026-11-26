"""R48 verifier: rebuild duplicates from the executor and check layer attribution."""
import argparse
import json
import sqlite3
from pathlib import Path

FAULTS = ['lost_return', 'late_commit']


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def observe(path):
    db = sqlite3.connect(path)
    try:
        effects = db.execute('select count(*) from effects').fetchone()[0]
        row = db.execute('select terminal, state from ops limit 1').fetchone()
    finally:
        db.close()
    return dict(effects=int(effects), terminal=bool(row[0]) if row else False,
                state=row[1] if row else 'pending')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--out')
    args = parser.parse_args()
    run = Path(args.run)
    completion = load(run / 'completion.json')
    freeze = load(run / 'freeze.json')
    seeds = freeze['seeds']
    tasks = completion['tasks']
    checks, passed, mismatches = [], [], []

    def check(name, actual, expected):
        checks.append(name)
        if actual == expected:
            passed.append(name)
        else:
            print(json.dumps({'check': name, 'actual': actual, 'expected': expected}))

    check('meta.failures', completion['failures'], [])
    check('meta.tasks', len(tasks), 2 * 2 * 2 * 2 * len(FAULTS) * len(seeds))

    attribution = []
    for task in tasks:
        directory = run / f"closure_{task['closure']}_stop_{task['stop']}"
        metric = observe(directory / 'private' / (task['workflow'] + '.sqlite'))
        if metric['effects'] != task['effects']:
            mismatches.append(dict(workflow=task['workflow'],
                                   recorded=task['effects'],
                                   observed=metric['effects']))
        expected = (task['replay'] == 'on' and task['closure'] == 'off'
                    and (task['fault'] == 'lost_return'
                         or not (task['cancel'] == 'on' and task['stop'] == 'on')))
        if (metric['effects'] > 1) != expected:
            attribution.append(dict(
                workflow=task['workflow'], effects=metric['effects'],
                replay=task['replay'], cancel=task['cancel'], stop=task['stop'],
                closure=task['closure'], fault=task['fault'], expected=expected))
    check('sqlite.recompute-mismatches', mismatches, [])
    check('layer.attribution', attribution, [])

    def select(**wanted):
        return [task for task in tasks
                if all(task[key] == value for key, value in wanted.items())]

    check('closure.on.zero-duplicates',
          sum(1 for task in tasks if task['closure'] == 'on' and task['duplicates'] > 0), 0)
    closure_on = select(closure='on', replay='on')
    check('closure.on.replay.on.complete',
          sum(1 for task in closure_on if task['complete']), len(closure_on))
    check('closure.on.replay.on.effects',
          sorted({task['effects'] for task in closure_on}), [1])

    lost = select(closure='off', replay='on', fault='lost_return')
    check('lost-return.duplicates', sum(1 for task in lost if task['duplicates'] > 0),
          len(lost))
    late_open = [task for task in select(closure='off', replay='on', fault='late_commit')
                 if not (task['cancel'] == 'on' and task['stop'] == 'on')]
    check('late.duplicates', sum(1 for task in late_open if task['duplicates'] > 0),
          len(late_open))
    late_stopped = select(closure='off', replay='on', fault='late_commit',
                          cancel='on', stop='on')
    check('late.cancel-stop.effects', sorted({task['effects'] for task in late_stopped}),
          [1])
    check('late.cancel-stop.duplicates',
          sum(1 for task in late_stopped if task['duplicates'] > 0), 0)

    replay_off = select(replay='off')
    check('replay-off.zero-duplicates',
          sum(1 for task in replay_off if task['duplicates'] > 0), 0)
    check('replay-off.closure-off.pauses',
          sum(1 for task in select(replay='off', closure='off')
              if task['terminal'] == 'complete'), 0)

    table = {}
    for replay in ('on', 'off'):
        for cancel in ('on', 'off'):
            for stop in ('on', 'off'):
                for closure in ('on', 'off'):
                    for fault in FAULTS:
                        rows = select(replay=replay, cancel=cancel, stop=stop,
                                      closure=closure, fault=fault)
                        table[f'{replay}/{cancel}/{stop}/{closure}/{fault}'] = dict(
                            effects=sorted({task['effects'] for task in rows}),
                            complete=sum(1 for task in rows if task['complete']),
                            count=len(rows))
    summary = dict(checks=len(checks), passed=len(passed),
                   status='pass' if len(passed) == len(checks) else 'fail',
                   mismatches=len(mismatches), attribution=attribution, cells=table)
    out = Path(args.out) if args.out else run / 'verification.json'
    out.write_text(json.dumps(dict(summary, failed=[c for c in checks if c not in passed]),
                              ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('status', 'checks', 'passed', 'mismatches')}))
    if summary['status'] != 'pass':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
