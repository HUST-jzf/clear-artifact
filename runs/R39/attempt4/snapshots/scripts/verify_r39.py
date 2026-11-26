"""Verify R39 from the service's own stats, transcripts, and pre-registered criteria."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
GUARDS = ['blind', 'evidence', 'clear']
FAULTS = ['none', 'lost_return', 'late_effect', 'late_effect_slow',
          'lost_before_commit']
RUNS = {'none': 4, 'lost_return': 6, 'late_effect': 6, 'late_effect_slow': 6,
        'lost_before_commit': 6}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    run = ROOT / args.run
    completion = json.loads((run / 'completion.json').read_text(encoding='utf-8'))
    tasks = completion['tasks']
    checks = []

    def check(name, got, want):
        checks.append(dict(name=name, ok=got == want, got=got, want=want))

    check('failures', completion['failures'], [])
    check('task_count', len(tasks), sum(RUNS.values()) * len(GUARDS))

    totals = {guard: dict(duplicates=0, stale=0, completed=0, runs=0,
                          lost_duplicates=0, late_duplicates=0, slow_duplicates=0,
                          retries=0)
              for guard in GUARDS}
    drains = set()
    for guard in GUARDS:
        for fault in FAULTS:
            for index in range(1, RUNS[fault] + 1):
                name = f'{guard}_{fault}_r{index}'
                directory = run / name
                result = json.loads((directory / 'result.json').read_text(
                    encoding='utf-8'))
                stats = json.loads((directory / 'private' / 'stats.json').read_text(
                    encoding='utf-8'))
                observed = stats.get(result['workflow'], dict(steps={}, rejected=0))
                rows = {step: int(observed['steps'].get(step, {}).get('rows', 0))
                        for step in STEPS}
                stale = {step: int(observed['steps'].get(step, {}).get('stale', 0))
                         for step in STEPS}
                duplicates = sum(max(0, rows[step] - 1) for step in STEPS)
                completed = all(rows[step] >= 1 for step in STEPS)
                check(f'{name}:rows', rows, result['rows'])
                check(f'{name}:duplicates', duplicates, result['duplicates'])
                check(f'{name}:stale', sum(stale.values()), sum(result['stale'].values()))
                check(f'{name}:completed', completed, result['completed'])
                check(f'{name}:key_leak', result['key_leak'], False)
                drains.add(result.get('drain_seconds'))
                if fault != 'none':
                    totals[guard]['runs'] += 1
                    totals[guard]['duplicates'] += duplicates
                    totals[guard]['stale'] += sum(stale.values())
                    totals[guard]['completed'] += int(completed)
                    totals[guard]['retries'] += int(result['retries_after_timeout'])
                    if fault == 'lost_return':
                        totals[guard]['lost_duplicates'] += duplicates
                    if fault == 'late_effect':
                        totals[guard]['late_duplicates'] += duplicates
                    if fault == 'late_effect_slow':
                        totals[guard]['slow_duplicates'] += duplicates

    check('drain_seconds_uniform_6', sorted(drains, key=str), [6.0])
    check('clear:no_duplicates', totals['clear']['duplicates'], 0)
    check('clear:no_stale', totals['clear']['stale'], 0)
    check('clear:completion_at_least_20_of_24', totals['clear']['completed'] >= 20, True)
    check('blind:lost_return_duplicates_at_least_1',
          totals['blind']['lost_duplicates'] >= 1, True)
    check('blind:late_effect_duplicates_at_least_1',
          totals['blind']['late_duplicates'] >= 1, True)
    check('blind:late_effect_slow_duplicates_at_least_1',
          totals['blind']['slow_duplicates'] >= 1, True)
    check('evidence:late_effect_slow_duplicates_at_least_1',
          totals['evidence']['slow_duplicates'] >= 1, True)
    check('evidence:lost_return_not_worse_than_blind',
          totals['evidence']['lost_duplicates'] <= totals['blind']['lost_duplicates'],
          True)

    passed = sum(1 for item in checks if item['ok'])
    body = dict(checks=len(checks), passed=passed,
                status='pass' if passed == len(checks) else 'fail',
                totals=totals,
                failed=[item for item in checks if not item['ok']][:20])
    with (run / 'verification.json').open('w', encoding='utf-8') as stream:
        json.dump(body, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({key: body[key] for key in ['checks', 'passed', 'status']}))
    print(json.dumps(body['totals'], ensure_ascii=False))
    raise SystemExit(0 if body['status'] == 'pass' else 1)


if __name__ == '__main__':
    main()
