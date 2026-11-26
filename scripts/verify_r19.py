"""Independent verification of an R19 run."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
STOP_ROWS = {'lost_return': 3, 'late_commit': 4, 'lost_before_commit': 2}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected(config, fault, policy):
    idem = config['idem']
    lifecycle = config['lifecycle']
    query = config['query']
    stop = STOP_ROWS[fault]
    forged = fault == 'lost_before_commit'
    if policy == 'clear':
        if forged:
            return dict(completed=False, duplicates=0, rows=stop, false_complete=False)
        if lifecycle == 'faithful' or query == 'faithful':
            return dict(completed=True, duplicates=0, rows=5, false_complete=False)
        return dict(completed=False, duplicates=0, rows=stop, false_complete=False)
    if policy == 'pause':
        return dict(completed=False, duplicates=0, rows=stop, false_complete=False)
    if policy in ('idem_retry', 'reauth_retry'):
        if forged or idem == 'on':
            return dict(completed=True, duplicates=0, rows=5, false_complete=False)
        return dict(completed=True, duplicates=1, rows=6, false_complete=False)
    if query == 'faithful':
        return dict(completed=True, duplicates=0, rows=5, false_complete=False)
    if query == 'stale':
        duplicates = 0 if idem == 'on' else 1
        return dict(completed=True, duplicates=duplicates, rows=5 + duplicates,
                    false_complete=False)
    if query == 'unavailable':
        return dict(completed=False, duplicates=0, rows=stop, false_complete=False)
    # forged
    return dict(completed=False, duplicates=0, rows=4, false_complete=True)


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
    expected_tasks = sum(len(item['seeds']) * len(item['faults']) * len(freeze['policies'])
                         for item in freeze['configs'])
    check('task_count', len(tasks) == expected_tasks, (len(tasks), expected_tasks))
    for name, digest in freeze['files'].items():
        source = ROOT / name
        check('frozen_file:' + name, source.exists() and sha(source) == digest)
    for name, digest in completion['sealed'].items():
        path = run / name
        check('sealed:' + name, path.exists() and sha(path) == digest)

    configs = {item['name']: item for item in freeze['configs']}
    index = {}
    for task in tasks:
        key = (task['config'], task['fault'], task['policy'], task['seed'])
        check('unique:' + ':'.join(map(str, key)), key not in index)
        index[key] = task
    check('index_size', len(index) == len(tasks))

    for name, config in configs.items():
        for fault in config['faults']:
            for policy in POLICIES:
                group = [index[(name, fault, policy, seed)] for seed in config['seeds']]
                want = expected(config, fault, policy)
                label = f'{name}:{fault}:{policy}'
                signatures = {(t['completed'], t['duplicates'], sum(t['rows'].values()),
                               t['false_complete']) for t in group}
                check('stable:' + label, len(signatures) == 1, sorted(signatures))
                for task in group:
                    got = dict(completed=task['completed'], duplicates=task['duplicates'],
                               rows=sum(task['rows'].values()),
                               false_complete=task['false_complete'])
                    check('expected:' + label, got == want, dict(got=got, want=want))
                    check('safe_definition:' + label,
                          task['safe'] == (task['completed'] and task['duplicates'] == 0
                                           and task['stale_rows'] == 0
                                           and all(n == 1 for n in task['rows'].values())))

    for name in configs:
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
    for name, config in configs.items():
        if config['lifecycle'] != 'lost':
            continue
        group = [task for task in tasks if task['config'] == name and task['policy'] == 'clear']
        if config['query'] == 'faithful':
            check(f'redundancy_completes:{name}', all(t['safe'] for t in group),
                  sum(1 for t in group if t['safe']))
        else:
            check(f'redundancy_pauses:{name}',
                  all(t['terminal'] == 'paused' for t in group),
                  sum(1 for t in group if t['terminal'] == 'paused'))
    forged = [task for task in tasks if task['policy'] == 'query_retry'
              and task['fault'] == 'lost_before_commit']
    expected_forged = sum(len(config['seeds']) for config in configs.values()
                          if config['query'] == 'forged')
    check('query_retry_false_completes',
          len(forged) == expected_forged and all(t['false_complete'] for t in forged),
          (len(forged), expected_forged, sum(t['false_complete'] for t in forged)))

    summary = {}
    for name in configs:
        summary[name] = {}
        for policy in POLICIES:
            group = [task for task in tasks if task['config'] == name and task['policy'] == policy]
            summary[name][policy] = dict(
                workflows=len(group), safe=sum(t['safe'] for t in group),
                completed=sum(t['completed'] for t in group),
                duplicates=sum(t['duplicates'] for t in group),
                false_complete=sum(1 for t in group if t['false_complete']),
                pauses=sum(1 for t in group if t['terminal'] == 'paused'),
                median_ms=round(sorted(t['elapsed_ns'] for t in group)[len(group) // 2] / 1e6, 2))

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
