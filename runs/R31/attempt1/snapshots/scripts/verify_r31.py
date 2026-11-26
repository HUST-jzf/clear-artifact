"""Independent verification of an R31 cross-tenant run."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected(policy):
    if policy in ('clear', 'pause'):
        return dict(completed=False, rows=2, duplicates=0, false_complete=False)
    if policy == 'query_retry':
        return dict(completed=False, rows=4, duplicates=0, false_complete=True)
    return dict(completed=True, rows=5, duplicates=0, false_complete=False)


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
    check('task_count', len(tasks) == 1 + len(freeze['policies']) * len(freeze['seeds']),
          len(tasks))
    for name, digest in freeze['files'].items():
        source = ROOT / name
        check('frozen_file:' + name, source.exists() and sha(source) == digest)
    for name, digest in completion['sealed'].items():
        path = run / name
        check('sealed:' + name, path.exists() and sha(path) == digest)

    donor = [t for t in tasks if t['workflow'] == freeze['donor']]
    check('donor_present', len(donor) == 1, len(donor))
    check('donor_completed', donor and donor[0]['completed'], donor and donor[0]['completed'])

    index = {}
    for task in tasks:
        if task['workflow'] == freeze['donor']:
            continue
        key = (task['policy'], task['seed'])
        check('unique:' + ':'.join(map(str, key)), key not in index)
        index[key] = task
    check('index_size', len(index) == len(freeze['policies']) * len(freeze['seeds']),
          len(index))

    for policy in freeze['policies']:
        group = [index[(policy, seed)] for seed in freeze['seeds']]
        want = expected(policy)
        signatures = {(t['completed'], t['duplicates'], sum(t['rows'].values()),
                       t['false_complete']) for t in group}
        check('stable:' + policy, len(signatures) == 1, sorted(signatures))
        for task in group:
            got = dict(completed=task['completed'],
                       rows=sum(task['rows'].values()),
                       duplicates=task['duplicates'],
                       false_complete=task['false_complete'])
            check('expected:' + policy, got == want, dict(got=got, want=want))
            check('attach_rows:' + policy,
                  task['rows']['attach'] == (1 if want['rows'] == 5 else 0),
                  task['rows']['attach'])

    query = [t for t in tasks if t['policy'] == 'query_retry']
    check('query_retry_accepts_forgery',
          all(t['false_complete'] for t in query),
          sum(t['false_complete'] for t in query))
    clear = [t for t in tasks if t['policy'] == 'clear']
    check('clear_rejects_forgery',
          all(t['terminal'] == 'paused' and not t['false_complete'] for t in clear),
          [t['terminal'] for t in clear][:3])
    check('clear_no_duplicates', all(t['duplicates'] == 0 for t in clear))

    stats = json.loads((run / 'tenant' / 'private' / 'stats.json')
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

    summary = {}
    for policy in freeze['policies']:
        group = [t for t in tasks if t['policy'] == policy]
        summary[policy] = dict(
            workflows=len(group), safe=sum(t['safe'] for t in group),
            completed=sum(t['completed'] for t in group),
            duplicates=sum(t['duplicates'] for t in group),
            false_complete=sum(t['false_complete'] for t in group),
            paused=sum(1 for t in group if t['terminal'] == 'paused'))

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
