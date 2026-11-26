"""R44 verifier: recompute the equal-capability comparison from task results."""
import argparse
import json
import statistics
from pathlib import Path

FAULTS = ['lost_return', 'late_effect', 'lost_before_commit']
POLICIES_A = ['fenced', 'dedup_versioned', 'dedup_fresh']
POLICIES_B = ['fenced', 'dedup_versioned', 'dedup_unversioned']


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--out')
    args = parser.parse_args()
    run = Path(args.run)
    completion = load(run / 'completion.json')
    tasks = completion['tasks']
    checks, passed = [], []

    def check(name, actual, expected):
        checks.append(name)
        if actual == expected:
            passed.append(name)
        else:
            print(json.dumps({'check': name, 'actual': actual, 'expected': expected}))

    a = [t for t in tasks if t['scenario'] == 'A']
    b = [t for t in tasks if t['scenario'] == 'B']
    check('meta.failures', completion['failures'], [])
    check('meta.tasks', len(tasks), 198)
    check('meta.scenario-a', len(a), 180)
    check('meta.scenario-b', len(b), 18)
    for fault in FAULTS:
        for policy in POLICIES_A:
            check(f'a.count.{fault}.{policy}',
                  len([t for t in a if t['fault'] == fault and t['policy'] == policy]), 20)
    for fault in FAULTS:
        fenced = [t for t in a if t['fault'] == fault and t['policy'] == 'fenced']
        versioned = [t for t in a if t['fault'] == fault and t['policy'] == 'dedup_versioned']
        fresh = [t for t in a if t['fault'] == fault and t['policy'] == 'dedup_fresh']
        check(f'a.safe.fenced.{fault}', sum(1 for t in fenced if t['safe']), 20)
        check(f'a.dup.fenced.{fault}', sum(t['duplicates'] for t in fenced), 0)
        check(f'a.safe.versioned.{fault}', sum(1 for t in versioned if t['safe']), 20)
        check(f'a.dup.versioned.{fault}', sum(t['duplicates'] for t in versioned), 0)
        check(f'a.complete.fresh.{fault}', sum(1 for t in fresh if t['completed']), 20)
        check(f'a.safe.fresh.{fault}', sum(1 for t in fresh if t['safe']),
              20 if fault == 'lost_before_commit' else 0)
        check(f'a.dup.fresh.{fault}', sum(t['duplicates'] for t in fresh),
              0 if fault == 'lost_before_commit' else 20)
    late = [t for t in a if t['fault'] == 'late_effect' and t['policy'] == 'fenced']
    check('a.stale-rejection.late_effect', sum(t['rejected'] for t in late), 20)

    def median(values):
        return statistics.median(values)

    fenced_all = [t for t in a if t['policy'] == 'fenced']
    versioned_all = [t for t in a if t['policy'] == 'dedup_versioned']
    check('overhead.requests.fenced-gt-versioned',
          median([t['requests'] for t in fenced_all]) >
          median([t['requests'] for t in versioned_all]), True)
    check('overhead.bytes.fenced-gt-versioned',
          median([t['bytes'] for t in fenced_all]) >
          median([t['bytes'] for t in versioned_all]), True)

    for policy in POLICIES_B:
        rows = [t for t in b if t['policy'] == policy]
        check(f'b.count.{policy}', len(rows), 6)
        if policy == 'dedup_unversioned':
            check(f'b.false-complete.{policy}', sum(1 for t in rows if t['false_complete']), 6)
            check(f'b.binding.{policy}', sum(1 for t in rows if t['binding_ok']), 0)
            check(f'b.intents.{policy}',
                  sorted({tuple(t['intents']) for t in rows}), [('seat:12A',)])
        else:
            check(f'b.false-complete.{policy}', sum(1 for t in rows if t['false_complete']), 0)
            check(f'b.binding.{policy}', sum(1 for t in rows if t['binding_ok']), 6)
            check(f'b.rows.{policy}', sorted({t['total_rows'] for t in rows}), [2])

    summary = dict(
        checks=len(checks), passed=len(passed),
        status='pass' if len(passed) == len(checks) else 'fail',
        metrics=dict(
            a=dict(fenced=dict(requests=median([t['requests'] for t in fenced_all]),
                               bytes=median([t['bytes'] for t in fenced_all]),
                               elapsed_ms=median([t['elapsed_ns'] / 1e6 for t in fenced_all])),
                   dedup_versioned=dict(
                       requests=median([t['requests'] for t in versioned_all]),
                       bytes=median([t['bytes'] for t in versioned_all]),
                       elapsed_ms=median([t['elapsed_ns'] / 1e6 for t in versioned_all]))),
            b=dict(fenced=dict(requests=median([t['requests'] for t in b
                                               if t['policy'] == 'fenced'])),
                   dedup_versioned=dict(requests=median([t['requests'] for t in b
                                                        if t['policy'] == 'dedup_versioned'])))))
    out = Path(args.out) if args.out else run / 'verification.json'
    out.write_text(
        json.dumps(dict(summary, failed=[c for c in checks if c not in passed]),
                   ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('status', 'checks', 'passed')}))
    if summary['status'] != 'pass':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
