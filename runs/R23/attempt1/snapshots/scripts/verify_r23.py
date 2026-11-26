"""Independent verification of an R23 key-stability run."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ['clear', 'idem_retry', 'idem_fresh', 'pause']
FAULTS = ['lost_return', 'late_commit']
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected(fault, policy):
    """Rows and duplicates under `idempotency=on`, faithful evidence."""
    stop = 3 if fault == 'lost_return' else 4
    if policy == 'clear':
        return dict(completed=True, duplicates=0, rows=5)
    if policy == 'pause':
        return dict(completed=False, duplicates=0, rows=stop)
    if policy == 'idem_retry':
        return dict(completed=True, duplicates=0, rows=5)
    return dict(completed=True, duplicates=1, rows=6)


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
    check('task_count', len(tasks) == len(freeze['policies']) * len(freeze['faults'])
          * len(freeze['seeds']), len(tasks))
    for name, digest in freeze['files'].items():
        source = ROOT / name
        check('frozen_file:' + name, source.exists() and sha(source) == digest)
    for name, digest in completion['sealed'].items():
        path = run / name
        check('sealed:' + name, path.exists() and sha(path) == digest)

    index = {}
    for task in tasks:
        key = (task['fault'], task['policy'], task['seed'])
        check('unique:' + ':'.join(map(str, key)), key not in index)
        index[key] = task
    check('index_size', len(index) == len(tasks))

    for fault in freeze['faults']:
        for policy in freeze['policies']:
            group = [index[(fault, policy, seed)] for seed in freeze['seeds']]
            want = expected(fault, policy)
            label = f'{fault}:{policy}'
            signatures = {(t['completed'], t['duplicates'], sum(t['rows'].values()))
                          for t in group}
            check('stable:' + label, len(signatures) == 1, sorted(signatures))
            for task in group:
                got = dict(completed=task['completed'], duplicates=task['duplicates'],
                           rows=sum(task['rows'].values()))
                check('expected:' + label, got == want, dict(got=got, want=want))
                check('false_complete:' + label, task['false_complete'] is False)

    stats = json.loads((run / 'idem_on' / 'private' / 'stats.json')
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

    def group(fault, policy):
        return [t for t in tasks if t['fault'] == fault and t['policy'] == policy]

    stable = [t for f in FAULTS for t in group(f, 'idem_retry')]
    fresh = [t for f in FAULTS for t in group(f, 'idem_fresh')]
    check('stable_key_no_duplicates', all(t['duplicates'] == 0 for t in stable),
          sum(t['duplicates'] for t in stable))
    check('fresh_key_duplicates', all(t['duplicates'] == 1 for t in fresh),
          [t['duplicates'] for t in fresh])
    check('fresh_key_completes', all(t['completed'] for t in fresh),
          sum(t['completed'] for t in fresh))
    clear = [t for f in FAULTS for t in group(f, 'clear')]
    check('clear_no_duplicates', all(t['duplicates'] == 0 for t in clear))
    check('clear_safe', all(t['safe'] for t in clear),
          sum(t['safe'] for t in clear))

    summary = {}
    for policy in freeze['policies']:
        group = [t for t in tasks if t['policy'] == policy]
        summary[policy] = dict(
            workflows=len(group), safe=sum(t['safe'] for t in group),
            completed=sum(t['completed'] for t in group),
            duplicates=sum(t['duplicates'] for t in group),
            pauses=sum(1 for t in group if t['terminal'] == 'paused'),
            false_complete=sum(t['false_complete'] for t in group))

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
