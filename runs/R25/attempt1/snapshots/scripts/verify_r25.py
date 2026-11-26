"""Independent verification of an R25 payment-domain run."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['authorize', 'capture', 'settle', 'notify']
POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']
FAULTS = ['lost_return', 'late_commit']
CHARGE = 2500


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected(idem, policy):
    if policy in ('clear', 'query_retry'):
        return dict(completed=True, rows=4, duplicates=0, double_charge=False)
    if policy == 'pause':
        return dict(completed=False, rows=2, duplicates=0, double_charge=False)
    if idem == 'on':
        return dict(completed=True, rows=4, duplicates=0, double_charge=False)
    return dict(completed=True, rows=5, duplicates=1, double_charge=True)


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
    check('task_count', len(tasks) == len(freeze['idempotency']) * len(freeze['faults'])
          * len(freeze['policies']) * len(freeze['seeds']), len(tasks))
    check('step_names', freeze['steps'] == STEPS, freeze['steps'])
    for name, digest in freeze['files'].items():
        source = ROOT / name
        check('frozen_file:' + name, source.exists() and sha(source) == digest)
    for name, digest in completion['sealed'].items():
        path = run / name
        check('sealed:' + name, path.exists() and sha(path) == digest)

    index = {}
    for task in tasks:
        key = (task['idempotency'], task['fault'], task['policy'], task['seed'])
        check('unique:' + ':'.join(map(str, key)), key not in index)
        index[key] = task
    check('index_size', len(index) == len(tasks))

    for idem in freeze['idempotency']:
        for fault in freeze['faults']:
            for policy in freeze['policies']:
                group = [index[(idem, fault, policy, seed)] for seed in freeze['seeds']]
                want = expected(idem, policy)
                label = f'{idem}:{fault}:{policy}'
                signatures = {(t['completed'], t['duplicates'],
                               sum(t['rows'].values()), t['double_charge'])
                              for t in group}
                check('stable:' + label, len(signatures) == 1, sorted(signatures))
                for task in group:
                    got = dict(completed=task['completed'],
                               rows=sum(task['rows'].values()),
                               duplicates=task['duplicates'],
                               double_charge=task['double_charge'])
                    check('expected:' + label, got == want, dict(got=got, want=want))
                    check('false_complete:' + label, task['false_complete'] is False)
                    if task['completed']:
                        check('charged_once_or_twice:' + label,
                              task['captured'] == CHARGE * (2 if want['duplicates'] else 1),
                              task['captured'])

    for idem in freeze['idempotency']:
        config = f'idem_{idem}'
        stats = json.loads((run / config / 'private' / 'stats.json')
                           .read_text(encoding='utf-8'))
        group = [t for t in tasks if t['config'] == config]
        check('stats_keys:' + config, set(stats) == {t['workflow'] for t in group},
              (len(stats), len(group)))
        mismatched = []
        for task in group:
            served = stats.get(task['workflow'], {})
            rows = {step: int(served.get(step, {}).get('rows', 0)) for step in STEPS}
            if rows != task['rows']:
                mismatched.append(dict(workflow=task['workflow'], served=rows,
                                       recorded=task['rows']))
        check('stats_match:' + config, not mismatched, mismatched[:2])

    clear = [t for t in tasks if t['policy'] == 'clear']
    check('clear_safe', all(t['safe'] for t in clear), sum(t['safe'] for t in clear))
    check('clear_no_double_charge',
          all(not t['double_charge'] for t in clear))
    double = [t for t in tasks if t['double_charge']]
    check('double_charge_only_without_idempotency',
          all(t['idempotency'] == 'off' for t in double),
          len(double))

    summary = {}
    for idem in freeze['idempotency']:
        for policy in freeze['policies']:
            group = [t for t in tasks if t['idempotency'] == idem and t['policy'] == policy]
            summary[f'idem_{idem}'] = summary.get(f'idem_{idem}', {})
            summary[f'idem_{idem}'][policy] = dict(
                workflows=len(group), safe=sum(t['safe'] for t in group),
                completed=sum(t['completed'] for t in group),
                duplicates=sum(t['duplicates'] for t in group),
                double_charge=sum(t['double_charge'] for t in group),
                paused=sum(1 for t in group if t['terminal'] == 'paused'),
                captured=sum(t['captured'] for t in group))

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
