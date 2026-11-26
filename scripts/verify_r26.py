"""Independent verification of an R26 instrumentation-ladder run."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
LEVELS = [0, 1, 2, 3]
POLICIES = ['clear', 'idem_retry', 'query_retry']
FAULTS = ['lost_return', 'late_commit']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected(level, fault, policy):
    stop = 3 if fault == 'lost_return' else 4
    if policy == 'idem_retry':
        return dict(completed=True, rows=6, duplicates=1)
    if policy == 'query_retry':
        if level < 3:
            return dict(completed=False, rows=stop, duplicates=0)
        return dict(completed=True, rows=5, duplicates=0)
    if level < 2:
        return dict(completed=False, rows=0 if level == 0 else stop, duplicates=0)
    return dict(completed=True, rows=5, duplicates=0)


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
    check('task_count', len(tasks) == len(freeze['levels']) * len(freeze['faults'])
          * len(freeze['policies']) * len(freeze['seeds']), len(tasks))
    for name, digest in freeze['files'].items():
        source = ROOT / name
        check('frozen_file:' + name, source.exists() and sha(source) == digest)
    for name, digest in completion['sealed'].items():
        path = run / name
        check('sealed:' + name, path.exists() and sha(path) == digest)

    index = {}
    for task in tasks:
        key = (task['level'], task['fault'], task['policy'], task['seed'])
        check('unique:' + ':'.join(map(str, key)), key not in index)
        index[key] = task
    check('index_size', len(index) == len(tasks))

    for level in freeze['levels']:
        for fault in freeze['faults']:
            for policy in freeze['policies']:
                group = [index[(level, fault, policy, seed)] for seed in freeze['seeds']]
                want = expected(level, fault, policy)
                label = f'L{level}:{fault}:{policy}'
                signatures = {(t['completed'], t['duplicates'], sum(t['rows'].values()))
                              for t in group}
                check('stable:' + label, len(signatures) == 1, sorted(signatures))
                for task in group:
                    got = dict(completed=task['completed'],
                               rows=sum(task['rows'].values()),
                               duplicates=task['duplicates'])
                    check('expected:' + label, got == want, dict(got=got, want=want))
                    check('false_complete:' + label, task['false_complete'] is False)

    for level in freeze['levels']:
        config = f'L{level}'
        stats = json.loads((run / config / 'private' / 'stats.json')
                           .read_text(encoding='utf-8'))
        group = [t for t in tasks if t['config'] == config]
        registered = {t['workflow'] for t in group if sum(t['rows'].values()) > 0}
        check('stats_cover_registered:' + config, registered <= set(stats),
              (len(stats), len(registered)))
        mismatched = []
        for task in group:
            served = stats.get(task['workflow'], {})
            rows = {step: int(served.get(step, {}).get('rows', 0)) for step in STEPS}
            if rows != task['rows']:
                mismatched.append(dict(workflow=task['workflow'], served=rows,
                                       recorded=task['rows']))
        check('stats_match:' + config, not mismatched, mismatched[:2])

    clear = [t for t in tasks if t['policy'] == 'clear']
    check('clear_never_duplicates', all(t['duplicates'] == 0 for t in clear),
          sum(t['duplicates'] for t in clear))
    for level in freeze['levels']:
        group = [t for t in clear if t['level'] == level]
        check(f'clear_no_duplicates_at_L{level}',
              all(t['duplicates'] == 0 for t in group),
              sum(t['duplicates'] for t in group))
        if level >= 2:
            check(f'clear_safe_at_L{level}', all(t['safe'] for t in group),
                  sum(t['safe'] for t in group))

    summary = {}
    for level in freeze['levels']:
        summary[f'L{level}'] = {}
        for policy in freeze['policies']:
            group = [t for t in tasks if t['level'] == level and t['policy'] == policy]
            summary[f'L{level}'][policy] = dict(
                workflows=len(group), safe=sum(t['safe'] for t in group),
                completed=sum(t['completed'] for t in group),
                duplicates=sum(t['duplicates'] for t in group),
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
