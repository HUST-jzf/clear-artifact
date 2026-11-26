"""Independent verification of an R30 evidence-outage run."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']
MODES = ['lifecycle_down', 'all_down']
IDEMPOTENCY = ['on', 'off']
FAULTS = ['lost_return', 'late_commit']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected(mode, idem, fault, policy):
    stop = 3 if fault == 'lost_return' else 4
    if policy == 'clear' and mode == 'lifecycle_down':
        # The effect index is still up; CLEAR falls back to it.
        return dict(completed=True, rows=5, duplicates=0, stale_rows=0)
    if policy in ('clear', 'pause'):
        return dict(completed=False, rows=stop, duplicates=0, stale_rows=0)
    if policy == 'query_retry' and mode == 'all_down':
        return dict(completed=False, rows=stop, duplicates=0, stale_rows=0)
    duplicates = 0 if (idem == 'on' or policy == 'query_retry') else 1
    return dict(completed=True, rows=5 + duplicates, duplicates=duplicates, stale_rows=0)


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
    check('task_count', len(tasks) == len(freeze['modes']) * len(freeze['idempotency'])
          * len(freeze['faults']) * len(freeze['policies']) * len(freeze['seeds']),
          len(tasks))
    for name, digest in freeze['files'].items():
        source = ROOT / name
        check('frozen_file:' + name, source.exists() and sha(source) == digest)
    for name, digest in completion['sealed'].items():
        path = run / name
        check('sealed:' + name, path.exists() and sha(path) == digest)

    index = {}
    for task in tasks:
        key = (task['mode'], task['idempotency'], task['fault'], task['policy'], task['seed'])
        check('unique:' + ':'.join(map(str, key)), key not in index)
        index[key] = task
    check('index_size', len(index) == len(tasks))

    for mode in freeze['modes']:
        for idem in freeze['idempotency']:
            for fault in freeze['faults']:
                for policy in freeze['policies']:
                    group = [index[(mode, idem, fault, policy, seed)]
                             for seed in freeze['seeds']]
                    want = expected(mode, idem, fault, policy)
                    label = f'{mode}:{idem}:{fault}:{policy}'
                    signatures = {(t['completed'], t['duplicates'],
                                   sum(t['rows'].values()), t['stale_rows'])
                                  for t in group}
                    check('stable:' + label, len(signatures) == 1, sorted(signatures))
                    for task in group:
                        got = dict(completed=task['completed'],
                                   rows=sum(task['rows'].values()),
                                   duplicates=task['duplicates'],
                                   stale_rows=task['stale_rows'])
                        check('expected:' + label, got == want, dict(got=got, want=want))
                        check('false_complete:' + label, task['false_complete'] is False)

    clear = [t for t in tasks if t['policy'] == 'clear']
    check('clear_no_duplicates', all(t['duplicates'] == 0 for t in clear),
          sum(t['duplicates'] for t in clear))
    check('clear_no_stale_rows', all(t['stale_rows'] == 0 for t in clear),
          sum(t['stale_rows'] for t in clear))
    blackout = [t for t in clear if t['mode'] == 'all_down']
    check('clear_paused_when_all_down',
          all(t['terminal'] == 'paused' for t in blackout),
          [t['terminal'] for t in blackout][:4])

    for mode in freeze['modes']:
        for idem in freeze['idempotency']:
            config = f'{mode}-{idem}'
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

    summary = {}
    for mode in freeze['modes']:
        for idem in freeze['idempotency']:
            for policy in freeze['policies']:
                group = [t for t in tasks if t['mode'] == mode
                         and t['idempotency'] == idem and t['policy'] == policy]
                summary[f'{mode}-{idem}'] = summary.get(f'{mode}-{idem}', {})
                summary[f'{mode}-{idem}'][policy] = dict(
                    workflows=len(group), completed=sum(t['completed'] for t in group),
                    safe=sum(t['safe'] for t in group),
                    duplicates=sum(t['duplicates'] for t in group),
                    paused=sum(1 for t in group if t['terminal'] == 'paused'))

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
