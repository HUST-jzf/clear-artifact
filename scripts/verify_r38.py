"""Verify R38 from the service's own stats and the recorded controller outcome."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
CLOSURES = ['faithful', 'absent']
FAULTS = ['late_effect', 'lost_before_commit']
POLICIES = {'faithful': ['clear', 'blind_retry', 'pause'],
            'absent': ['clear', 'clear_fenced', 'blind_retry', 'pause']}
SEEDS = list(range(1, 21))
EXPECTED = {
    ('faithful', 'late_effect', 'clear'): dict(rows=1, completed=True, rejected=0,
                                               terminal='complete', safe=True),
    ('faithful', 'late_effect', 'blind_retry'): dict(rows=2, completed=True, rejected=0,
                                                     terminal='complete', safe=False),
    ('faithful', 'late_effect', 'pause'): dict(rows=1, completed=False, rejected=0,
                                               terminal='pause', safe=False),
    ('faithful', 'lost_before_commit', 'clear'): dict(rows=1, completed=True, rejected=0,
                                                      terminal='complete', safe=True),
    ('faithful', 'lost_before_commit', 'blind_retry'): dict(rows=1, completed=True,
                                                            rejected=0,
                                                            terminal='complete', safe=True),
    ('faithful', 'lost_before_commit', 'pause'): dict(rows=0, completed=False, rejected=0,
                                                      terminal='pause', safe=False),
    ('absent', 'late_effect', 'clear'): dict(rows=1, completed=False, rejected=0,
                                             terminal='pause', safe=False),
    ('absent', 'late_effect', 'clear_fenced'): dict(rows=1, completed=True, rejected=1,
                                                    terminal='complete', safe=True),
    ('absent', 'late_effect', 'blind_retry'): dict(rows=2, completed=True, rejected=0,
                                                   terminal='complete', safe=False),
    ('absent', 'late_effect', 'pause'): dict(rows=1, completed=False, rejected=0,
                                             terminal='pause', safe=False),
    ('absent', 'lost_before_commit', 'clear'): dict(rows=0, completed=False, rejected=0,
                                                    terminal='pause', safe=False),
    ('absent', 'lost_before_commit', 'clear_fenced'): dict(rows=1, completed=True,
                                                           rejected=0,
                                                           terminal='complete', safe=True),
    ('absent', 'lost_before_commit', 'blind_retry'): dict(rows=1, completed=True,
                                                          rejected=0,
                                                          terminal='complete', safe=True),
    ('absent', 'lost_before_commit', 'pause'): dict(rows=0, completed=False, rejected=0,
                                                    terminal='pause', safe=False),
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
          sum(len(POLICIES[closure]) for closure in CLOSURES) * len(FAULTS) * len(SEEDS))
    for closure in CLOSURES:
        for fault in FAULTS:
            for policy in POLICIES[closure]:
                want = EXPECTED[(closure, fault, policy)]
                for seed in SEEDS:
                    name = f'{closure}_{fault}_{policy}_s{seed}'
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

    fence = json.loads((run / 'fence_check.json').read_text(encoding='utf-8'))
    check('fence:both_safe', fence['configs']['both']['duplicate_reachable'], False)
    check('fence:fence_only_duplicate',
          fence['configs']['fence_only']['duplicate_reachable'], True)
    check('fence:finalize_only_duplicate',
          fence['configs']['finalize_only']['duplicate_reachable'], True)

    passed = sum(1 for item in checks if item['ok'])
    body = dict(checks=len(checks), passed=passed,
                status='pass' if passed == len(checks) else 'fail',
                cells={f'{closure}/{fault}/{policy}': EXPECTED[(closure, fault, policy)]
                       for closure in CLOSURES for fault in FAULTS
                       for policy in POLICIES[closure]},
                failed=[item for item in checks if not item['ok']][:20])
    with (run / 'verification.json').open('w', encoding='utf-8') as stream:
        json.dump(body, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({key: body[key] for key in ['checks', 'passed', 'status']}))
    raise SystemExit(0 if body['status'] == 'pass' else 1)


if __name__ == '__main__':
    main()
