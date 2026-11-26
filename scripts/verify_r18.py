"""Independent verification of an R18 run.

Checks the pre-registered matrix in docs/R18_evidence_plane_degradation_protocol.md and
recomputes every metric from the service's own state.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAULTS = ['lost_return', 'late_commit']
FAULT_STEP = {'lost_return': 'attach', 'late_commit': 'commit'}
POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected(config, fault, policy):
    idem, query = config.split('_', 1)
    stop_rows = 3 if fault == 'lost_return' else 4
    if policy == 'clear':
        return dict(completed=True, duplicates=0, rows=5, stopped_at=None)
    if policy == 'pause':
        return dict(completed=False, duplicates=0, rows=stop_rows,
                    stopped_at=FAULT_STEP[fault])
    if policy in ('idem_retry', 'reauth_retry'):
        if idem == 'on':
            return dict(completed=True, duplicates=0, rows=5, stopped_at=None)
        return dict(completed=True, duplicates=1, rows=6, stopped_at=None)
    if query == 'faithful':
        return dict(completed=True, duplicates=0, rows=5, stopped_at=None)
    if query == 'stale':
        duplicates = 0 if idem == 'on' else 1
        return dict(completed=True, duplicates=duplicates, rows=5 + duplicates,
                    stopped_at=None)
    return dict(completed=False, duplicates=0, rows=stop_rows,
                stopped_at=FAULT_STEP[fault])


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
    configs, seeds = completion['configs'], completion['seeds']
    check('no_failures', not failures, failures[:2])
    check('task_count', len(tasks) == len(configs) * len(FAULTS) * len(POLICIES) * len(seeds),
          len(tasks))
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

    for config in configs:
        for fault in FAULTS:
            for policy in POLICIES:
                group = [index[(config, fault, policy, seed)] for seed in seeds]
                want = expected(config, fault, policy)
                label = f'{config}:{fault}:{policy}'
                signatures = {(t['completed'], t['duplicates'], sum(t['rows'].values()),
                               t['stopped_at']) for t in group}
                check('stable:' + label, len(signatures) == 1, sorted(signatures))
                for task in group:
                    got = dict(completed=task['completed'], duplicates=task['duplicates'],
                               rows=sum(task['rows'].values()), stopped_at=task['stopped_at'])
                    check('expected:' + label, got == want, dict(got=got, want=want))
                    check('safe_definition:' + label,
                          task['safe'] == (task['completed'] and task['duplicates'] == 0
                                           and task['stale_rows'] == 0
                                           and all(n == 1 for n in task['rows'].values())))

    for config in configs:
        stats = json.loads((run / config / 'private' / 'stats.json').read_text(encoding='utf-8'))
        group = [task for task in tasks if task['config'] == config]
        check(f'stats_keys:{config}', set(stats) == {t['workflow'] for t in group},
              (len(stats), len(group)))
        mismatched = []
        for task in group:
            served = stats.get(task['workflow'], {})
            rows = {step: int(served.get(step, {}).get('rows', 0)) for step in STEPS}
            if rows != task['rows']:
                mismatched.append(dict(workflow=task['workflow'], served=rows,
                                       recorded=task['rows']))
        check(f'stats_match:{config}', not mismatched, mismatched[:2])

    for config in configs:
        if config.startswith('off_'):
            for fault in FAULTS:
                clear = [index[(config, fault, 'clear', seed)] for seed in seeds]
                check(f'discriminator:{config}:{fault}:clear',
                      all(t['safe'] for t in clear),
                      sum(1 for t in clear if t['safe']))
    for config in configs:
        if config.startswith('on_'):
            retries = [task for task in tasks if task['config'] == config
                       and task['policy'] in ('idem_retry', 'reauth_retry')]
            check(f'ceiling:{config}', all(t['duplicates'] == 0 for t in retries),
                  sum(t['duplicates'] for t in retries))
    check('clear_no_stale', all(t['stale_rows'] == 0 for t in tasks if t['policy'] == 'clear'))
    check('clear_no_duplicates', all(t['duplicates'] == 0 for t in tasks if t['policy'] == 'clear'))

    summary = {}
    for config in configs:
        summary[config] = {}
        for policy in POLICIES:
            group = [task for task in tasks if task['config'] == config and task['policy'] == policy]
            summary[config][policy] = dict(
                workflows=len(group), safe=sum(t['safe'] for t in group),
                completed=sum(t['completed'] for t in group),
                duplicates=sum(t['duplicates'] for t in group),
                pauses=sum(1 for t in group if t['terminal'] == 'paused'),
                post_calls=sum(t['post_calls'] for t in group),
                http_calls=sum(t['http_calls'] for t in group),
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
