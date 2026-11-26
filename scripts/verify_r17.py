"""Independent R17 verifier: structural checks over the Z3 report."""
import argparse
import json
from pathlib import Path


def verify(path):
    report = json.loads(Path(path).read_text(encoding='utf-8'))
    checks = []

    def check(name, ok, detail=None):
        checks.append(dict(name=name, ok=bool(ok), detail=detail))

    check('tool-is-z3', report.get('tool') == 'z3', report.get('tool'))
    check('summary-pass', report.get('summary', {}).get('status') == 'pass',
          report.get('summary'))
    theorems = report.get('theorems', {})
    for name in ('T1_retry_soundness', 'T2_admission_atomicity', 'T4_requalification',
                 'all_assumptions_safe'):
        check('unsat:' + name, theorems.get(name, {}).get('result') == 'unsat',
              theorems.get(name))
    check('unsat:T3', theorems.get('T3_incomplete_evidence_impossibility', {}).get('result')
          == 'unsat', theorems.get('T3_incomplete_evidence_impossibility'))
    check('unsat:base', report.get('base', {}).get('result') == 'unsat',
          report.get('base'))

    ablations = report.get('ablations', {})
    expected_last = {
        'no_A1_faithful_query': 'admit_retry_atomic',
        'no_A2_lifecycle_closure': 'admit_retry_atomic',
        'no_A3_version_binding': 'admit_retry_atomic',
        'no_A4_atomic_admission': 'retry_write',
    }
    check('ablation-count', len(ablations) == 4, len(ablations))
    for name, last in expected_last.items():
        item = ablations.get(name, {})
        trace = (item.get('counterexample') or {}).get('trace') or []
        check('sat:' + name, item.get('result') == 'sat', item.get('result'))
        check('trace:' + name, bool(trace) and trace[-1] == last,
              dict(trace=trace, expected_last=last))
        depth = (item.get('counterexample') or {}).get('depth')
        check('depth:' + name, isinstance(depth, int) and 1 <= depth <= report.get('depth', 10),
              depth)

    total = len(checks)
    passed = sum(1 for item in checks if item['ok'])
    return dict(checks=checks, checks_total=total, checks_passed=passed,
                failed=[item for item in checks if not item['ok']])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('report', nargs='?', default='formal/z3_report.json')
    parser.add_argument('--output')
    args = parser.parse_args()
    result = verify(args.report)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + '\n', encoding='utf-8')
    print(json.dumps(dict(checks_total=result['checks_total'],
                          checks_passed=result['checks_passed'],
                          failed=result['failed']), ensure_ascii=False))
    raise SystemExit(0 if not result['failed'] else 1)


if __name__ == '__main__':
    main()
