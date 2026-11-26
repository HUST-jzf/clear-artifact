"""Verify R36 from the service's own stats and the recorded controller outcome."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
PROFILES = ['buffered', 'immediate']
FAULTS = ['late_effect', 'lost_before_commit']
POLICIES = ['clear', 'clear_fenced', 'frontier', 'blind_retry']
SEEDS = list(range(1, 21))
EXPECTED = {
    ('buffered', 'late_effect', 'clear'): dict(rows=1, completed=False, rejected=0,
                                               terminal='pause', safe=False),
    ('buffered', 'late_effect', 'clear_fenced'): dict(rows=1, completed=True,
                                                      rejected=1, terminal='complete',
                                                      safe=True),
    ('buffered', 'late_effect', 'frontier'): dict(rows=1, completed=True, rejected=1,
                                                  terminal='complete', safe=True),
    ('buffered', 'late_effect', 'blind_retry'): dict(rows=2, completed=True,
                                                     rejected=0, terminal='complete',
                                                     safe=False),
    ('buffered', 'lost_before_commit', 'clear'): dict(rows=0, completed=False,
                                                      rejected=0, terminal='pause',
                                                      safe=False),
    ('buffered', 'lost_before_commit', 'clear_fenced'): dict(rows=1, completed=True,
                                                             rejected=0,
                                                             terminal='complete', safe=True),
    ('buffered', 'lost_before_commit', 'frontier'): dict(rows=1, completed=True,
                                                         rejected=0, terminal='complete',
                                                         safe=True),
    ('buffered', 'lost_before_commit', 'blind_retry'): dict(rows=1, completed=True,
                                                            rejected=0,
                                                            terminal='complete', safe=True),
    ('immediate', 'late_effect', 'clear'): dict(rows=1, completed=False, rejected=0,
                                                terminal='pause', safe=False),
    ('immediate', 'late_effect', 'clear_fenced'): dict(rows=1, completed=True,
                                                       rejected=1, terminal='complete',
                                                       safe=True),
    ('immediate', 'late_effect', 'frontier'): dict(rows=1, completed=False, rejected=0,
                                                   terminal='pause', safe=False),
    ('immediate', 'late_effect', 'blind_retry'): dict(rows=2, completed=True,
                                                      rejected=0, terminal='complete',
                                                      safe=False),
    ('immediate', 'lost_before_commit', 'clear'): dict(rows=0, completed=False,
                                                       rejected=0, terminal='pause',
                                                       safe=False),
    ('immediate', 'lost_before_commit', 'clear_fenced'): dict(rows=1, completed=True,
                                                              rejected=0,
                                                              terminal='complete', safe=True),
    ('immediate', 'lost_before_commit', 'frontier'): dict(rows=0, completed=False,
                                                          rejected=0, terminal='pause',
                                                          safe=False),
    ('immediate', 'lost_before_commit', 'blind_retry'): dict(rows=1, completed=True,
                                                             rejected=0,
                                                             terminal='complete', safe=True),
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
          len(PROFILES) * len(FAULTS) * len(POLICIES) * len(SEEDS))
    for profile in PROFILES:
        for fault in FAULTS:
            for policy in POLICIES:
                want = EXPECTED[(profile, fault, policy)]
                for seed in SEEDS:
                    name = f'{profile}_{fault}_{policy}_s{seed}'
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
                    safe = (completed and duplicates == 0 and sum(stale.values()) == 0)
                    check(f'{name}:attach_rows', rows['attach'], want['rows'])
                    check(f'{name}:completed', completed, want['completed'])
                    check(f'{name}:rejected', int(observed['rejected']), want['rejected'])
                    check(f'{name}:terminal', result['terminal'], want['terminal'])
                    check(f'{name}:safe', safe, want['safe'])

    passed = sum(1 for item in checks if item['ok'])
    body = dict(checks=len(checks), passed=passed,
                status='pass' if passed == len(checks) else 'fail',
                cells={f'{profile}/{fault}/{policy}': EXPECTED[(profile, fault, policy)]
                       for profile in PROFILES for fault in FAULTS for policy in POLICIES},
                failed=[item for item in checks if not item['ok']][:20])
    with (run / 'verification.json').open('w', encoding='utf-8') as stream:
        json.dump(body, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({key: body[key] for key in ['checks', 'passed', 'status']}))
    raise SystemExit(0 if body['status'] == 'pass' else 1)


if __name__ == '__main__':
    main()
