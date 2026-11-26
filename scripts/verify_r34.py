"""Verify R34 from the service's own stats and the recorded controller outcomes."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
FAULTS = ['lost_return', 'lost_before_commit']
MECHANISMS = ['none', 'lease', 'unique']
SEEDS = list(range(1, 21))
EXPECTED = {
    ('lost_return', 'none'): dict(rows=1, duplicates=0, safe=True, writes=0),
    ('lost_return', 'lease'): dict(rows=1, duplicates=0, safe=True, writes=0),
    ('lost_return', 'unique'): dict(rows=1, duplicates=0, safe=True, writes=0),
    ('lost_before_commit', 'none'): dict(rows=2, duplicates=1, safe=False, writes=2),
    ('lost_before_commit', 'lease'): dict(rows=1, duplicates=0, safe=True, writes=1),
    ('lost_before_commit', 'unique'): dict(rows=1, duplicates=0, safe=True, writes=1),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    run = ROOT / args.run
    completion = json.loads((run / 'completion.json').read_text(encoding='utf-8'))
    checks = []

    def check(name, got, want):
        checks.append(dict(name=name, ok=got == want, got=got, want=want))

    check('failures', completion['failures'], [])
    check('task_count', len(completion['tasks']),
          len(FAULTS) * len(MECHANISMS) * len(SEEDS))
    for fault in FAULTS:
        for mechanism in MECHANISMS:
            want = EXPECTED[(fault, mechanism)]
            for seed in SEEDS:
                name = f'{fault}_{mechanism}_s{seed}'
                directory = run / name
                result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
                stats = json.loads((directory / 'private' / 'stats.json').read_text(
                    encoding='utf-8'))
                observed = stats.get(result['workflow'], {})
                rows = {step: int(observed.get(step, {}).get('rows', 0)) for step in STEPS}
                duplicates = sum(max(0, rows[step] - 1) for step in STEPS)
                safe = (all(rows[step] >= 1 for step in STEPS) and duplicates == 0
                        and all(int(observed.get(step, {}).get('stale', 0)) == 0
                                for step in STEPS))
                terminals = {owner: result['controllers'][owner]['terminal']
                             for owner in result['controllers']}
                check(f'{name}:attach_rows', rows['attach'], want['rows'])
                check(f'{name}:duplicates', duplicates, want['duplicates'])
                check(f'{name}:safe', safe, want['safe'])
                check(f'{name}:writes', sum(outcome['writes']
                                            for outcome in result['controllers'].values()),
                      want['writes'])
                check(f'{name}:all_complete', set(terminals.values()), {'complete'})

    passed = sum(1 for item in checks if item['ok'])
    body = dict(checks=len(checks), passed=passed,
                status='pass' if passed == len(checks) else 'fail',
                cells={f'{fault}/{mechanism}': EXPECTED[(fault, mechanism)]
                       for fault in FAULTS for mechanism in MECHANISMS},
                failed=[item for item in checks if not item['ok']][:20])
    with (run / 'verification.json').open('w', encoding='utf-8') as stream:
        json.dump(body, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({key: body[key] for key in ['checks', 'passed', 'status']}))
    raise SystemExit(0 if body['status'] == 'pass' else 1)


if __name__ == '__main__':
    main()
