"""Independent verification of an R21 run."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']
FAULTS = ['lost_return', 'late_commit']
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected(idem, fault, policy):
    stop = 3 if fault == 'lost_return' else 4
    if policy == 'clear':
        return dict(completed=True, duplicates=0, rows=5)
    if policy == 'pause':
        return dict(completed=False, duplicates=0, rows=stop)
    if policy == 'query_retry':
        return dict(completed=True, duplicates=0, rows=5)
    if idem == 'on':
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
    check('task_count', len(tasks) == len(freeze['configs']) * len(FAULTS)
          * len(POLICIES) * len(freeze['seeds']), len(tasks))
    for name, digest in freeze['files'].items():
        source = ROOT / name
        check('frozen_file:' + name, source.exists() and sha(source) == digest)
    for name, digest in completion['sealed'].items():
        path = run / name
        check('sealed:' + name, path.exists() and sha(path) == digest)

    index = {}
    for task in tasks:
        key = (task['config'], task['fault'], task['policy'], task['seed'])
        check('unique:' + ':'.join(map(str, key)), key not in index)
        index[key] = task
    check('index_size', len(index) == len(tasks))

    for config in freeze['configs']:
        name, idem = config['name'], config['idem']
        for fault in FAULTS:
            for policy in POLICIES:
                group = [index[(name, fault, policy, seed)] for seed in freeze['seeds']]
                want = expected(idem, fault, policy)
                label = f'{name}:{fault}:{policy}'
                signatures = {(t['completed'], t['duplicates'], sum(t['rows'].values()))
                              for t in group}
                check('stable:' + label, len(signatures) == 1, sorted(signatures))
                for task in group:
                    got = dict(completed=task['completed'], duplicates=task['duplicates'],
                               rows=sum(task['rows'].values()))
                    check('expected:' + label, got == want, dict(got=got, want=want))
                    check('false_complete:' + label, task['false_complete'] is False)

    for config in freeze['configs']:
        name = config['name']
        stats = json.loads((run / name / 'private' / 'stats.json').read_text(encoding='utf-8'))
        group = [task for task in tasks if task['config'] == name]
        check(f'stats_keys:{name}', set(stats) == {t['workflow'] for t in group},
              (len(stats), len(group)))
        mismatched = []
        for task in group:
            served = stats.get(task['workflow'], {})
            rows = {step: int(served.get(step, {}).get('rows', 0)) for step in STEPS}
            if rows != task['rows']:
                mismatched.append(dict(workflow=task['workflow'], served=rows,
                                       recorded=task['rows']))
        check(f'stats_match:{name}', not mismatched, mismatched[:2])

    clear = [task for task in tasks if task['policy'] == 'clear']
    check('clear_no_duplicates', all(t['duplicates'] == 0 for t in clear))
    check('clear_no_false_complete', all(not t['false_complete'] for t in clear))
    check('clear_safe_concurrency', all(t['safe'] for t in clear),
          sum(1 for t in clear if t['safe']))
    check('systems_recorded', len(completion['systems']) == len(freeze['configs']),
          completion['systems'])
    check('throughput_positive', all(item['throughput'] > 0 for item in completion['systems']))
    check('latency_recorded', all(item['p95_ms'] > 0 for item in completion['systems']))

    summary = {}
    for config in freeze['configs']:
        name = config['name']
        summary[name] = {}
        for policy in POLICIES:
            group = [task for task in tasks if task['config'] == name and task['policy'] == policy]
            summary[name][policy] = dict(
                workflows=len(group), safe=sum(t['safe'] for t in group),
                completed=sum(t['completed'] for t in group),
                duplicates=sum(t['duplicates'] for t in group),
                pauses=sum(1 for t in group if t['terminal'] == 'paused'),
                median_ms=round(sorted(t['elapsed_ns'] for t in group)[len(group) // 2] / 1e6, 2))

    report = dict(run=args.run, checks=len(checks),
                  passed=sum(1 for item in checks if item['passed']),
                  failed=[item for item in checks if not item['passed']],
                  systems=completion['systems'], summary=summary,
                  status='pass' if all(item['passed'] for item in checks) else 'fail')
    with (run / 'verification.json').open('w', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(dict(checks=report['checks'], passed=report['passed'],
                          status=report['status']), ensure_ascii=False))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
