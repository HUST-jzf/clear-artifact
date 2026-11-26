"""Independent verification of an R16 run.

Both baselines are checked against the pre-registered expectation that a
documented durable-execution + idempotency-key configuration behaves like the
R15 `idem_retry` policy: no duplicate when the service honours the key, one
duplicate when it does not, and no protection against revocation.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAULTS = ['lost_return', 'late_commit', 'revoke_after_reserve', 'revoke_after_commit']
BASELINES = ['temporal', 'langgraph']
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected(config, fault):
    if fault == 'lost_return':
        duplicates = 0 if config == 'idem_on' else 1
        return dict(completed=True, duplicates=duplicates, stale_rows=0, rows=5 + duplicates)
    if fault == 'late_commit':
        duplicates = 0 if config == 'idem_on' else 1
        return dict(completed=True, duplicates=duplicates, stale_rows=0, rows=5 + duplicates)
    if fault == 'revoke_after_reserve':
        return dict(completed=True, duplicates=0, stale_rows=3, rows=5)
    return dict(completed=True, duplicates=0, stale_rows=1, rows=5)


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
    baselines, configs, seeds = completion['baselines'], completion['configs'], completion['seeds']
    check('no_failures', not failures, failures[:2])
    check('task_count', len(tasks) == len(baselines) * len(configs) * len(FAULTS) * len(seeds),
          len(tasks))
    for name, digest in freeze['files'].items():
        source = ROOT / name
        check('frozen_file:' + name, source.exists() and sha(source) == digest)
    for name, digest in completion['sealed'].items():
        path = run / name
        check('sealed:' + name, path.exists() and sha(path) == digest)

    index = {}
    for task in tasks:
        key = (task['baseline'], task['config'], task['fault'], task['seed'])
        check('unique:' + ':'.join(map(str, key)), key not in index)
        index[key] = task
    check('index_size', len(index) == len(tasks))

    for baseline in baselines:
        for config in configs:
            for fault in FAULTS:
                group = [index[(baseline, config, fault, seed)] for seed in seeds]
                want = expected(config, fault)
                signatures = {(t['completed'], t['duplicates'], t['stale_rows'],
                               sum(t['rows'].values())) for t in group}
                label = f'{baseline}:{config}:{fault}'
                check('stable:' + label, len(signatures) == 1, sorted(signatures))
                for task in group:
                    got = dict(completed=task['completed'], duplicates=task['duplicates'],
                               stale_rows=task['stale_rows'], rows=sum(task['rows'].values()))
                    check('expected:' + label, got == want, dict(got=got, want=want))
                    check('safe_definition:' + label,
                          task['safe'] == (task['completed'] and task['duplicates'] == 0
                                           and task['stale_rows'] == 0
                                           and all(n == 1 for n in task['rows'].values())))
                if len(baselines) == 2:
                    other = 'langgraph' if baseline == 'temporal' else 'temporal'
                    twin = [index[(other, config, fault, seed)] for seed in seeds]
                    check('baselines_agree:' + label,
                          [(t['completed'], t['duplicates'], t['stale_rows'],
                            tuple(t['rows'].values())) for t in group]
                          == [(t['completed'], t['duplicates'], t['stale_rows'],
                               tuple(t['rows'].values())) for t in twin])

    for config in configs:
        stats = json.loads((run / config / 'private' / 'stats.json').read_text(encoding='utf-8'))
        group = [t for t in tasks if t['config'] == config]
        check(f'stats_keys:{config}', set(stats) == {t['workflow'] for t in group},
              (len(stats), len(group)))
        mismatched = []
        for task in group:
            served = stats.get(task['workflow'], {})
            rows = {step: int(served.get(step, {}).get('rows', 0)) for step in STEPS}
            stale = {step: int(served.get(step, {}).get('stale', 0)) for step in STEPS}
            if rows != task['rows'] or stale != task['stale']:
                mismatched.append(dict(workflow=task['workflow'], served=rows,
                                       recorded=task['rows']))
        check(f'stats_match:{config}', not mismatched, mismatched[:2])

    on = [t for t in tasks if t['config'] == 'idem_on']
    off = [t for t in tasks if t['config'] == 'idem_off']
    check('idem_on_no_duplicates', all(t['duplicates'] == 0 for t in on))
    check('idem_off_duplicate_workflows',
          sum(1 for t in off if t['duplicates'] > 0) == len(baselines) * 2 * len(seeds),
          sum(1 for t in off if t['duplicates'] > 0))
    check('all_stale_on_revoke',
          all(t['stale_rows'] > 0 for t in tasks if t['fault'].startswith('revoke')))

    summary = {}
    for baseline in baselines:
        summary[baseline] = {}
        for config in configs:
            group = [t for t in tasks if t['baseline'] == baseline and t['config'] == config]
            summary[baseline][config] = dict(
                workflows=len(group), safe=sum(t['safe'] for t in group),
                completed=sum(t['completed'] for t in group),
                duplicates=sum(t['duplicates'] for t in group),
                stale_rows=sum(t['stale_rows'] for t in group),
                median_ms=round(sorted(t['elapsed_ns'] for t in group)[len(group) // 2] / 1e6, 2))
            for fault in FAULTS:
                cell = [t for t in group if t['fault'] == fault]
                summary[baseline][config][fault] = dict(
                    workflows=len(cell), safe=sum(t['safe'] for t in cell),
                    completed=sum(t['completed'] for t in cell),
                    duplicates=sum(t['duplicates'] for t in cell),
                    stale_rows=sum(t['stale_rows'] for t in cell))

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
