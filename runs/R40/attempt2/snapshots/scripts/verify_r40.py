"""Verify R40 from the service's own per-operation stats and the pre-registered criteria."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
STEP_OF = {'create_ticket': 'create', 'reserve_seat': 'reserve',
           'attach_passenger': 'attach', 'commit_ticket': 'commit',
           'notify_user': 'notify'}
GUARDS = ['blind', 'evidence', 'clear']
SCENARIOS = ['intent_change', 'no_fence_repair']
RUNS = 6


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    run = ROOT / args.run
    completion = json.loads((run / 'completion.json').read_text(encoding='utf-8'))
    freeze = json.loads((run / 'freeze.json').read_text(encoding='utf-8'))
    checks = []

    def check(name, got, want):
        checks.append(dict(name=name, ok=got == want, got=got, want=want))

    check('failures', completion['failures'], [])
    check('task_count', len(completion['tasks']), len(SCENARIOS) * len(GUARDS) * RUNS)
    check('model', freeze['model'], 'deepseek-flash')
    check('drain_seconds', freeze['drain_seconds'], 6.0)

    totals = {key: dict(runs=0, duplicates=0, mixed=0, stale=0, residual=0,
                        paused=0, repaired=0, recovered=0, phase1_completed=0,
                        followed=0, completed=0)
              for key in [f'{scenario}/{guard}' for scenario in SCENARIOS
                          for guard in GUARDS]}
    drains = set()
    for scenario in SCENARIOS:
        for guard in GUARDS:
            bucket = totals[f'{scenario}/{guard}']
            for index in range(1, RUNS + 1):
                name = f'{scenario}_{guard}_r{index}'
                directory = run / name
                result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
                stats = json.loads((directory / 'private' / 'stats.json').read_text(
                    encoding='utf-8'))
                observed = stats.get(result['workflow'], dict(steps={}, ops=[], rejected=0))
                ops = observed.get('ops', [])
                rows = {step: int(observed['steps'].get(step, {}).get('rows', 0))
                        for step in STEPS}
                committed = {step: int(observed['steps'].get(step, {}).get('committed', 0))
                             for step in STEPS}
                duplicates = sum(max(0, int(entry['rows']) - 1) for entry in ops)
                mixed = sum(1 for entry in ops if len(entry.get('intents') or []) > 1)
                intents = sorted({intent for entry in ops for intent in entry.get('intents') or []})
                attach = [intent for intent in intents if intent.startswith('ticket:attach:')]
                stale = (result['followed'] and not any(
                    intent.endswith(':' + str(result['last_attach_seat'])) for intent in attach))
                residual = sum(1 for intent in attach
                               if not intent.endswith(':' + str(result['last_attach_seat']))) \
                    if result['followed'] else 0
                completed = all(count >= 1 for count in committed.values())
                paused = [STEP_OF.get(name, name) for name in result.get('paused_list') or []]
                recovered = bool(result['repaired'] and paused
                                 and all(committed[step] >= 1 for step in paused))
                check(f'{name}:rows', rows, result['rows'])
                check(f'{name}:duplicates', duplicates, result['duplicates'])
                check(f'{name}:mixed', mixed, result['mixed_binding'])
                check(f'{name}:stale', stale, result['stale_completion'])
                check(f'{name}:residual', residual, result['residual_old_intent'])
                check(f'{name}:completed', completed, result['completed'])
                check(f'{name}:recovered', recovered, result['recovered'])
                check(f'{name}:key_leak', result['key_leak'], False)
                drains.add(result.get('drain_seconds'))
                bucket['runs'] += 1
                bucket['duplicates'] += duplicates
                bucket['mixed'] += mixed
                bucket['stale'] += int(stale)
                bucket['residual'] += residual
                bucket['paused'] += int(result['paused_steps'] > 0)
                bucket['repaired'] += int(result['repaired'])
                bucket['recovered'] += int(result['recovered'])
                bucket['phase1_completed'] += int(result['phase1_completed'])
                bucket['followed'] += int(result['followed'])
                bucket['completed'] += int(completed)

    check('drain_seconds_uniform_6', sorted(drains, key=str), [6.0])

    intent = {guard: totals[f'intent_change/{guard}'] for guard in GUARDS}
    check('intent:clear_no_mixed_binding', intent['clear']['mixed'], 0)
    check('intent:clear_no_stale_completion', intent['clear']['stale'], 0)
    check('intent:clear_followed_at_least_4', intent['clear']['followed'] >= 4, True)
    check('intent:blind_mixed_at_least_1', intent['blind']['mixed'] >= 1, True)
    check('intent:evidence_unsafe_at_least_1',
          intent['evidence']['mixed'] + intent['evidence']['stale'] >= 1, True)

    repair = {guard: totals[f'no_fence_repair/{guard}'] for guard in GUARDS}
    check('repair:clear_paused_6', repair['clear']['paused'], 6)
    check('repair:clear_repaired_6', repair['clear']['repaired'], 6)
    check('repair:clear_recovered_6', repair['clear']['recovered'], 6)
    check('repair:clear_no_duplicates', repair['clear']['duplicates'], 0)
    check('repair:blind_completed_6', repair['blind']['phase1_completed'], 6)
    check('repair:evidence_completed_6', repair['evidence']['phase1_completed'], 6)

    passed = sum(1 for item in checks if item['ok'])
    body = dict(checks=len(checks), passed=passed,
                status='pass' if passed == len(checks) else 'fail',
                totals=totals,
                failed=[item for item in checks if not item['ok']][:20])
    with (run / 'verification.json').open('w', encoding='utf-8') as stream:
        json.dump(body, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(dict(checks=body['checks'], passed=body['passed'],
                          status=body['status'])))
    print(json.dumps(body['totals'], ensure_ascii=False))
    raise SystemExit(0 if body['status'] == 'pass' else 1)


if __name__ == '__main__':
    main()
