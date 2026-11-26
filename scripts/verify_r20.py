"""Independent verification of an R20 run."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected(policy, idem, placements):
    faults = len(placements)
    first = min(index for index, _ in placements)
    if policy == 'clear':
        return dict(completed=True, duplicates=0, rows=5, stopped_at=None)
    if policy == 'pause':
        return dict(completed=False, duplicates=0, rows=first + 1,
                    stopped_at=STEPS[first])
    if policy == 'query_retry':
        return dict(completed=True, duplicates=0, rows=5, stopped_at=None)
    if idem == 'on':
        return dict(completed=True, duplicates=0, rows=5, stopped_at=None)
    return dict(completed=True, duplicates=faults, rows=5 + faults, stopped_at=None)


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
    check('task_count', len(tasks) == len(freeze['configs']) * len(freeze['seeds'])
          * len(freeze['policies']), len(tasks))
    for name, digest in freeze['files'].items():
        source = ROOT / name
        check('frozen_file:' + name, source.exists() and sha(source) == digest)
    for name, digest in completion['sealed'].items():
        path = run / name
        check('sealed:' + name, path.exists() and sha(path) == digest)

    index = {}
    for task in tasks:
        key = (task['config'], task['policy'], task['seed'])
        check('unique:' + ':'.join(map(str, key)), key not in index)
        index[key] = task
    check('index_size', len(index) == len(tasks))

    for config in freeze['configs']:
        idem = config.rsplit('-', 1)[1]
        for seed in freeze['seeds']:
            group = [index[(config, policy, seed)] for policy in POLICIES]
            placements = group[0]['placements']
            label = f'{config}:S{seed}'
            check('placement_consistent:' + label,
                  all(task['placements'] == placements for task in group), placements)
            placement_key = f"{group[0]['campaign']}:{seed}"
            check('placement_frozen:' + label,
                  placements == freeze['placements'][placement_key],
                  dict(recorded=placements, frozen=freeze['placements'][placement_key]))
            check('placement_valid:' + label,
                  len({index for index, _ in placements}) == len(placements), placements)
            for task in group:
                want = expected(task['policy'], idem, placements)
                got = dict(completed=task['completed'], duplicates=task['duplicates'],
                           rows=sum(task['rows'].values()), stopped_at=task['stopped_at'])
                check('expected:' + label + ':' + task['policy'], got == want,
                      dict(got=got, want=want))
                check('false_complete:' + label + ':' + task['policy'],
                      task['false_complete'] is False)
                check('stale:' + label + ':' + task['policy'], task['stale_rows'] == 0)

    for config in freeze['configs']:
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

    clear = [task for task in tasks if task['policy'] == 'clear']
    check('clear_safe', all(t['safe'] for t in clear), sum(1 for t in clear if t['safe']))
    double = [task for task in tasks if task['campaign'] == 'double_lost'
              and task['policy'] == 'idem_retry' and task['idem'] == 'off']
    check('double_duplicates', all(t['duplicates'] == 2 for t in double),
          sorted({t['duplicates'] for t in double}))

    summary = {}
    for config in freeze['configs']:
        summary[config] = {}
        for policy in POLICIES:
            group = [task for task in tasks if task['config'] == config and task['policy'] == policy]
            summary[config][policy] = dict(
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
