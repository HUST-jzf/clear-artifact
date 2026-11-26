"""Verify R27: decorator path reproduces R4's CLEAR cells."""
import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ['smolagents', 'pydantic_ai', 'llamaindex']
SEEDS = [1, 2, 3, 4, 5]
CASES = ['C01_fail_before', 'C02_lost_return', 'C03_late_commit', 'C04_revoke',
         'C05_query_unavailable', 'C06_closure_missing', 'C07_idempotent_lost',
         'C08_normal']
EXPECTED = {
    'C01_fail_before': dict(terminal='complete', rows=1),
    'C02_lost_return': dict(terminal='complete', rows=1),
    'C03_late_commit': dict(terminal='complete', rows=1),
    'C04_revoke': dict(terminal='pause', rows=0),
    'C05_query_unavailable': dict(terminal='pause', rows=1),
    'C06_closure_missing': dict(terminal='complete', rows=1),
    'C07_idempotent_lost': dict(terminal='complete', rows=1),
    'C08_normal': dict(terminal='complete', rows=1),
}
LIMITS = dict(guard_core_lines=60, adapter_change_lines=1, config_items=2,
              business_changes=0)


def core_lines(path):
    text = Path(path).read_text(encoding='utf-8')
    tree = ast.parse(text)
    node = next(item for item in tree.body
                if isinstance(item, ast.FunctionDef) and item.name == 'guarded')
    lines = text.splitlines()[node.body[0].lineno - 1:node.body[-1].end_lineno]
    return sum(1 for line in lines if line.strip() and not line.strip().startswith('#'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    run = ROOT / args.run
    checks = []

    def check(name, got, want):
        checks.append(dict(name=name, ok=got == want, got=got, want=want))

    for source in SOURCES:
        completion = json.loads((run / f'completion_{source}.json').read_text(encoding='utf-8'))
        check(f'{source}:failures', completion['failures'], [])
        check(f'{source}:adapter_change_lines', completion['adapter_change_lines'],
              LIMITS['adapter_change_lines'])
        check(f'{source}:business_changes', completion['business_changes'],
              LIMITS['business_changes'])
        check(f'{source}:config_items', len(completion['config_items']),
              LIMITS['config_items'])
        tasks = {(task['seed'], task['case']): task for task in completion['tasks']}
        check(f'{source}:task_count', len(tasks), len(SEEDS) * len(CASES))
        for seed in SEEDS:
            for case in CASES:
                want = EXPECTED[case]
                directory = run / f'{source}_s{seed}_{case}'
                result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
                state = json.loads((directory / 'state.json').read_text(encoding='utf-8'))
                task = tasks.get((seed, case), {})
                check(f'{source}:s{seed}:{case}:terminal', result['terminal'],
                      want['terminal'])
                check(f'{source}:s{seed}:{case}:rows', len(state['writes']), want['rows'])
                check(f'{source}:s{seed}:{case}:recorded_terminal', task.get('terminal'),
                      want['terminal'])
                baseline = ROOT / 'runs' / f'R4_{source}' / f'seed{seed}' / f'{case}_clear'
                base_result = json.loads((baseline / 'result.json').read_text(encoding='utf-8'))
                base_state = json.loads((baseline / 'state.json').read_text(encoding='utf-8'))
                check(f'{source}:s{seed}:{case}:baseline_terminal', result['terminal'],
                      base_result['terminal'])
                check(f'{source}:s{seed}:{case}:baseline_rows', len(state['writes']),
                      len(base_state['writes']))

    measured = core_lines(ROOT / 'scripts/r27_guard.py')
    check('guard_core_lines', measured <= LIMITS['guard_core_lines'], True)
    check('guard_core_lines_recorded',
          json.loads((run / 'freeze_smolagents.json').read_text(encoding='utf-8'))['guard_core_lines'],
          measured)

    passed = sum(1 for item in checks if item['ok'])
    body = dict(checks=len(checks), passed=passed,
                status='pass' if passed == len(checks) else 'fail',
                guard_core_lines=measured,
                failed=[item for item in checks if not item['ok']][:20])
    with (run / 'verification.json').open('w', encoding='utf-8') as stream:
        json.dump(body, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({key: body[key] for key in ['checks', 'passed', 'status',
                                                 'guard_core_lines']}))
    raise SystemExit(0 if body['status'] == 'pass' else 1)


if __name__ == '__main__':
    main()
