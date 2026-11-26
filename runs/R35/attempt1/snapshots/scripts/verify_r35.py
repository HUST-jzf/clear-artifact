"""Verify R35 from the service's own stats and the recorded controller outcome."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = ['lost_return', 'lost_before_commit', 'revoke_race']
POLICIES = ['clear', 'verify_retry']
SEEDS = list(range(1, 21))
EXPECTED = {
    ('lost_return', 'clear'): dict(rows=1, stale=0, completed=True, terminal='complete',
                                   safe=True),
    ('lost_return', 'verify_retry'): dict(rows=1, stale=0, completed=True,
                                          terminal='complete', safe=True),
    ('lost_before_commit', 'clear'): dict(rows=1, stale=0, completed=True,
                                          terminal='complete', safe=True),
    ('lost_before_commit', 'verify_retry'): dict(rows=1, stale=0, completed=True,
                                                 terminal='complete', safe=True),
    ('revoke_race', 'clear'): dict(rows=0, stale=0, completed=False, terminal='pause',
                                   safe=False),
    ('revoke_race', 'verify_retry'): dict(rows=1, stale=1, completed=True,
                                          terminal='complete', safe=False),
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
          len(CONDITIONS) * len(POLICIES) * len(SEEDS))
    for condition in CONDITIONS:
        for policy in POLICIES:
            want = EXPECTED[(condition, policy)]
            for seed in SEEDS:
                name = f'{condition}_{policy}_s{seed}'
                directory = run / name
                result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
                stats = json.loads((directory / 'private' / 'stats.json').read_text(
                    encoding='utf-8'))
                observed = stats.get(result['workflow'], {})
                rows = {step: int(observed.get(step, {}).get('rows', 0))
                        for step in ['create', 'reserve', 'attach', 'commit', 'notify']}
                stale = {step: int(observed.get(step, {}).get('stale', 0))
                         for step in rows}
                duplicates = sum(max(0, rows[step] - 1) for step in rows)
                completed = all(rows[step] >= 1 for step in rows)
                safe = (completed and duplicates == 0 and sum(stale.values()) == 0)
                check(f'{name}:attach_rows', rows['attach'], want['rows'])
                check(f'{name}:attach_stale', stale['attach'], want['stale'])
                check(f'{name}:completed', completed, want['completed'])
                check(f'{name}:terminal', result['terminal'], want['terminal'])
                check(f'{name}:safe', safe, want['safe'])

    passed = sum(1 for item in checks if item['ok'])
    body = dict(checks=len(checks), passed=passed,
                status='pass' if passed == len(checks) else 'fail',
                cells={f'{condition}/{policy}': EXPECTED[(condition, policy)]
                       for condition in CONDITIONS for policy in POLICIES},
                failed=[item for item in checks if not item['ok']][:20])
    with (run / 'verification.json').open('w', encoding='utf-8') as stream:
        json.dump(body, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({key: body[key] for key in ['checks', 'passed', 'status']}))
    raise SystemExit(0 if body['status'] == 'pass' else 1)


if __name__ == '__main__':
    main()
