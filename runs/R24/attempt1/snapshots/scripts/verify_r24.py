"""Independent verification of an R24 resume run."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
POLICIES = ['clear', 'clear_replay', 'clear_resume', 'idem_retry']
CONDITIONS = ['revoke_at_attach', 'blackout_at_attach']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected(condition, policy):
    if condition == 'revoke_at_attach':
        table = {
            'clear': dict(completed=False, rows=2, duplicates=0, stale_rows=0, repairs=0),
            'clear_replay': dict(completed=True, rows=5, duplicates=0, stale_rows=0, repairs=1),
            'clear_resume': dict(completed=True, rows=5, duplicates=0, stale_rows=0, repairs=1),
            'idem_retry': dict(completed=True, rows=5, duplicates=0, stale_rows=3, repairs=0),
        }
    else:
        table = {
            'clear': dict(completed=False, rows=3, duplicates=0, stale_rows=0, repairs=0),
            'clear_replay': dict(completed=True, rows=6, duplicates=1, stale_rows=0, repairs=1),
            'clear_resume': dict(completed=True, rows=5, duplicates=0, stale_rows=0, repairs=1),
            'idem_retry': dict(completed=True, rows=6, duplicates=1, stale_rows=0, repairs=0),
        }
    return table[policy]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    run = (ROOT / args.run).resolve()
    checks = []

    def check(name, passed, detail=None):
        checks.append(dict(name=name, passed=bool(passed), detail=detail))
        if not passed:
            print('FAIL', name, detail)

    completion = json.loads((run / 'completion.json').read_text(encoding='utf-8'))
    freeze = json.loads((run / 'freeze.json').read_text(encoding='utf-8'))
    tasks, failures = completion['tasks'], completion['failures']
    check('no_failures', not failures, failures[:2])
    check('task_count', len(tasks) == len(freeze['conditions']) * len(freeze['policies'])
          * len(freeze['seeds']), len(tasks))
    for name, digest in freeze['files'].items():
        source = ROOT / name
        check('frozen_file:' + name, source.exists() and sha(source) == digest)
    for name, digest in completion['sealed'].items():
        path = run / name
        check('sealed:' + name, path.exists() and sha(path) == digest)

    index = {}
    for task in tasks:
        key = (task['condition'], task['policy'], task['seed'])
        check('unique:' + ':'.join(map(str, key)), key not in index)
        index[key] = task
    check('index_size', len(index) == len(tasks))

    for condition in freeze['conditions']:
        for policy in freeze['policies']:
            group = [index[(condition, policy, seed)] for seed in freeze['seeds']]
            want = expected(condition, policy)
            label = f'{condition}:{policy}'
            signatures = {(t['completed'], t['duplicates'], sum(t['rows'].values()),
                           t['stale_rows'], t['repairs']) for t in group}
            check('stable:' + label, len(signatures) == 1, sorted(signatures))
            for task in group:
                got = dict(completed=task['completed'],
                           rows=sum(task['rows'].values()),
                           duplicates=task['duplicates'],
                           stale_rows=task['stale_rows'], repairs=task['repairs'])
                check('expected:' + label, got == want, dict(got=got, want=want))
                check('false_complete:' + label, task['false_complete'] is False)

    stats = json.loads((run / 'idem_off' / 'private' / 'stats.json')
                       .read_text(encoding='utf-8'))
    check('stats_keys', set(stats) == {t['workflow'] for t in tasks},
          (len(stats), len(tasks)))
    mismatched = []
    for task in tasks:
        served = stats.get(task['workflow'], {})
        rows = {step: int(served.get(step, {}).get('rows', 0)) for step in STEPS}
        if rows != task['rows']:
            mismatched.append(dict(workflow=task['workflow'], served=rows,
                                   recorded=task['rows']))
    check('stats_match', not mismatched, mismatched[:2])

    resume = [t for t in tasks if t['policy'] == 'clear_resume']
    replay = [t for t in tasks if t['policy'] == 'clear_replay']
    check('resume_safe', all(t['safe'] for t in resume),
          sum(t['safe'] for t in resume))
    check('resume_no_duplicates', all(t['duplicates'] == 0 for t in resume),
          sum(t['duplicates'] for t in resume))
    check('replay_duplicates_on_blackout',
          all(t['duplicates'] == 1 for t in replay if t['condition'] == 'blackout_at_attach'),
          [t['duplicates'] for t in replay if t['condition'] == 'blackout_at_attach'])
    check('replay_safe_on_revoke',
          all(t['safe'] for t in replay if t['condition'] == 'revoke_at_attach'),
          sum(t['safe'] for t in replay if t['condition'] == 'revoke_at_attach'))

    summary = {}
    for condition in freeze['conditions']:
        summary[condition] = {}
        for policy in freeze['policies']:
            group = [t for t in tasks if t['condition'] == condition and t['policy'] == policy]
            summary[condition][policy] = dict(
                workflows=len(group), completed=sum(t['completed'] for t in group),
                safe=sum(t['safe'] for t in group),
                duplicates=sum(t['duplicates'] for t in group),
                stale_rows=sum(t['stale_rows'] for t in group),
                paused=sum(1 for t in group if t['terminal'] == 'paused'),
                repairs=sum(t['repairs'] for t in group))

    report = dict(run=args.run, checks=len(checks),
                  passed=sum(1 for item in checks if item['passed']),
                  failed=[item for item in checks if not item['passed']],
                  summary=summary,
                  status='pass' if all(item['passed'] for item in checks) else 'fail')
    with (run / 'verification.json').open('w', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(dict(checks=report['checks'], passed=report['passed'],
                          status=report['status']), ensure_ascii=False))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
