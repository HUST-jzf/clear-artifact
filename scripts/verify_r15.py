"""Independent verification of an R15 run.

Recomputes every metric from the recorded service observations, checks the
pre-registered matrix in docs/R15_end_to_end_workflow_protocol.md, and cross-checks
the service's own statistics written at shutdown.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAULTS = ['lost_return', 'late_commit', 'revoke_after_reserve', 'revoke_after_commit']
POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected(config, fault, policy):
    idem_on = config == 'idem_on'
    if policy == 'clear':
        if fault in ('lost_return', 'late_commit'):
            return dict(completed=True, duplicates=0, stale_rows=0, rows=5, stopped_at=None)
        if fault == 'revoke_after_reserve':
            return dict(completed=False, duplicates=0, stale_rows=0, rows=2, stopped_at='attach')
        return dict(completed=False, duplicates=0, stale_rows=0, rows=4, stopped_at='notify')
    if fault == 'lost_return':
        if policy == 'pause':
            return dict(completed=False, duplicates=0, stale_rows=0, rows=3, stopped_at='attach')
        retry = policy in ('idem_retry', 'reauth_retry')
        duplicates = 1 if retry and not idem_on else 0
        return dict(completed=True, duplicates=duplicates, stale_rows=0,
                    rows=5 + duplicates, stopped_at=None)
    if fault == 'late_commit':
        if policy == 'pause':
            return dict(completed=False, duplicates=0, stale_rows=0, rows=4, stopped_at='commit')
        retry = policy in ('idem_retry', 'reauth_retry')
        duplicates = 1 if retry and not idem_on else 0
        return dict(completed=True, duplicates=duplicates, stale_rows=0,
                    rows=5 + duplicates, stopped_at=None)
    if fault == 'revoke_after_reserve':
        return dict(completed=True, duplicates=0, stale_rows=3, rows=5, stopped_at=None)
    return dict(completed=True, duplicates=0, stale_rows=1, rows=5, stopped_at=None)


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
    check('no_infrastructure_failures', not failures, failures[:2])
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
                signatures = {(t['completed'], t['duplicates'], t['stale_rows'],
                               sum(t['rows'].values()), t['stopped_at']) for t in group}
                check(f'stable:{config}:{fault}:{policy}', len(signatures) == 1, sorted(signatures))
                label = f'{config}:{fault}:{policy}'
                for task in group:
                    got = dict(completed=task['completed'], duplicates=task['duplicates'],
                               stale_rows=task['stale_rows'],
                               rows=sum(task['rows'].values()),
                               stopped_at=task['stopped_at'])
                    check('expected:' + label, got == want, dict(got=got, want=want))
                    check('rows_consistent:' + label,
                          task['duplicates'] == sum(max(0, n - 1) for n in task['rows'].values()))
                    check('calls:' + label,
                          task['post_calls'] >= sum(1 for n in task['rows'].values() if n > 0))
                    check('safe_definition:' + label,
                          task['safe'] == (task['completed'] and task['duplicates'] == 0
                                           and task['stale_rows'] == 0
                                           and all(n == 1 for n in task['rows'].values())))

    for config in configs:
        stats = json.loads((run / config / 'private' / 'stats.json').read_text(encoding='utf-8'))
        group = [t for t in tasks if t['config'] == config]
        check(f'stats_keys:{config}', set(stats) == {t['workflow'] for t in group}, len(stats))
        for task in group:
            served = stats.get(task['workflow'], {})
            rows = {step: int(served.get(step, {}).get('rows', 0)) for step in STEPS}
            stale = {step: int(served.get(step, {}).get('stale', 0)) for step in STEPS}
            check(f'stats_rows:{config}:{task["workflow"]}', rows == task['rows'],
                  dict(served=rows, recorded=task['rows']))
            check(f'stats_stale:{config}:{task["workflow"]}', stale == task['stale'],
                  dict(served=stale, recorded=task['stale']))
        workflows = json.loads((run / config / 'private' / 'workflows.json')
                               .read_text(encoding='utf-8'))
        check(f'permits_settled:{config}',
              all(item['epoch'] >= 1 for item in workflows.values()), len(workflows))

    clear = [t for t in tasks if t['policy'] == 'clear']
    check('clear_safe_lost_late',
          sum(t['safe'] for t in clear if t['fault'] in ('lost_return', 'late_commit'))
          == len([t for t in clear if t['fault'] in ('lost_return', 'late_commit')]))
    check('clear_no_stale', all(t['stale_rows'] == 0 for t in clear))
    check('clear_no_duplicates', all(t['duplicates'] == 0 for t in clear))
    check('clear_pauses_on_revoke',
          all(t['terminal'] == 'paused' for t in clear if t['fault'].startswith('revoke')))

    off = [t for t in tasks if t['config'] == 'idem_off']
    on = [t for t in tasks if t['config'] == 'idem_on']
    check('idem_on_no_duplicates', all(t['duplicates'] == 0 for t in on))
    check('idem_off_retry_duplicates',
          sum(1 for t in off if t['duplicates'] > 0) == 4 * len(seeds),  # 2 faults x 2 retry policies
          sum(1 for t in off if t['duplicates'] > 0))
    check('idem_off_query_clean',
          all(t['duplicates'] == 0 for t in off
              if t['policy'] in ('query_retry', 'clear')))

    summary = {}
    for config in configs:
        summary[config] = {}
        for policy in POLICIES:
            group = [t for t in tasks if t['config'] == config and t['policy'] == policy]
            summary[config][policy] = dict(
                workflows=len(group), safe=sum(t['safe'] for t in group),
                completed=sum(t['completed'] for t in group),
                duplicates=sum(t['duplicates'] for t in group),
                stale_rows=sum(t['stale_rows'] for t in group),
                orphan=sum(t['orphan'] for t in group),
                pauses=sum(1 for t in group if t['terminal'] == 'paused'),
                post_calls=sum(t['post_calls'] for t in group),
                http_calls=sum(t['http_calls'] for t in group),
                median_ms=round(sorted(t['elapsed_ns'] for t in group)[len(group) // 2] / 1e6, 2))
        for fault in FAULTS:
            group = [t for t in tasks if t['config'] == config and t['fault'] == fault]
            summary[config][fault] = dict(
                workflows=len(group), safe=sum(t['safe'] for t in group),
                completed=sum(t['completed'] for t in group),
                duplicates=sum(t['duplicates'] for t in group),
                stale_rows=sum(t['stale_rows'] for t in group))

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
