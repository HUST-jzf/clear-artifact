"""Consolidate held-out source runs across seeds 0-9."""
import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALL_SOURCES = {
    'smolagents': [ROOT / 'runs/R4_smolagents/attempt1']
                   + [ROOT / f'runs/R4_smolagents/seed{s}' for s in range(1, 10)],
    'pydantic_ai': [ROOT / 'runs/R4_pydantic_ai/attempt1']
                   + [ROOT / f'runs/R4_pydantic_ai/seed{s}' for s in range(1, 10)],
    'llamaindex': [ROOT / 'runs/R4_llamaindex/attempt2']
                  + [ROOT / f'runs/R4_llamaindex/seed{s}' for s in range(1, 10)],
    'autogen': [ROOT / 'runs/R4_autogen/attempt2']
               + [ROOT / f'runs/R4_autogen/seed{s}' for s in range(1, 10)],
}
POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']
CASES = ['C01_fail_before', 'C02_lost_return', 'C03_late_commit', 'C04_revoke',
         'C05_query_unavailable', 'C06_closure_missing', 'C07_idempotent_lost', 'C08_normal']
CHECKS = []


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8')


def check(name, actual, expected):
    CHECKS.append(dict(name=name, ok=actual == expected, actual=actual, expected=expected))


def safe_task(result, state):
    writes = state.get('writes', [])
    rows = len(writes)
    stale = [item for item in writes
             if item.get('attempt', 0) > 1 and item.get('allowed') is not True]
    return dict(terminal=result['terminal'], rows=rows, duplicate=rows > 1,
                stale=bool(stale), safe=result['terminal'] == 'complete' and rows == 1 and not stale)


def wilson(success, total):
    if total == 0:
        return [0.0, 0.0]
    z = 1.959963984540054
    p = success / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / denominator
    return [round(center - half, 3), round(center + half, 3)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='runs/R4_seeds/attempt1')
    parser.add_argument('--sources', default='smolagents,pydantic_ai')
    parser.add_argument('--title', default='R4 held-out sources, 10-seed summary')
    args = parser.parse_args()
    sources = {name: ALL_SOURCES[name] for name in args.sources.split(',')}
    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'summary.json').exists():
        raise SystemExit('refusing to overwrite ' + str(out / 'summary.json'))

    summary = {'schema': 'r4_10seed_v1', 'sources': {}, 'total_tasks': 0}
    for source, runs in sources.items():
        aggregate = {policy: dict(tasks=0, safe=0, complete=0, duplicate=0, stale=0, pause=0)
                     for policy in POLICIES}
        conditions = {case: dict(seeds=0, safe=0, terminals=Counter(), rows=Counter(),
                                 duplicate=0, stale=0) for case in CASES}
        seed_aggregates = {}
        tasks = 0
        for seed, run in enumerate(runs):
            freeze = load(run / 'freeze.json')
            check(f'{source}:seed{seed}:seed-field', freeze.get('seed', 0), seed)
            check(f'{source}:seed{seed}:task-count-file', len(freeze['cases']) * len(freeze['policies']), 40)
            seed_aggregate = dict(tasks=0, safe=0, complete=0, duplicate=0, stale=0, clear_safe=0)
            for case in freeze['cases']:
                for policy in freeze['policies']:
                    directory = run / f"{case['id']}_{policy}"
                    result = load(directory / 'result.json')
                    state = load(directory / 'state.json')
                    item = safe_task(result, state)
                    entry = aggregate[policy]
                    entry['tasks'] += 1
                    entry['safe'] += item['safe']
                    entry['complete'] += item['terminal'] == 'complete'
                    entry['duplicate'] += item['duplicate']
                    entry['stale'] += item['stale']
                    entry['pause'] += item['terminal'] == 'pause'
                    seed_aggregate['tasks'] += 1
                    seed_aggregate['safe'] += item['safe']
                    seed_aggregate['complete'] += item['terminal'] == 'complete'
                    seed_aggregate['duplicate'] += item['duplicate']
                    seed_aggregate['stale'] += item['stale']
                    if policy == 'clear':
                        seed_aggregate['clear_safe'] += item['safe']
                        cond = conditions[case['id']]
                        cond['seeds'] += 1
                        cond['safe'] += item['safe']
                        cond['terminals'][item['terminal']] += 1
                        cond['rows'][item['rows']] += 1
                        cond['duplicate'] += item['duplicate']
                        cond['stale'] += item['stale']
                    tasks += 1
            seed_aggregates[str(seed)] = seed_aggregate
            check(f'{source}:seed{seed}:aggregate', seed_aggregate,
                  {'tasks': 40, 'safe': 16, 'complete': 29, 'duplicate': 11,
                   'stale': 2, 'clear_safe': 6})
        check(f'{source}:tasks', tasks, 400)
        check(f'{source}:runs', len(runs), 10)
        for policy, entry in aggregate.items():
            if policy == 'clear':
                check(f'{source}:clear:no-duplicate', entry['duplicate'], 0)
                check(f'{source}:clear:no-stale', entry['stale'], 0)
        for case, cond in conditions.items():
            expected_terminal = 'complete' if case not in ('C04_revoke', 'C05_query_unavailable') else 'pause'
            expected_safe = 10 if expected_terminal == 'complete' else 0
            expected_rows = 0 if case == 'C04_revoke' else 1
            check(f'{source}:{case}:terminal', dict(cond['terminals']), {expected_terminal: 10})
            check(f'{source}:{case}:rows', dict(cond['rows']), {expected_rows: 10})
            check(f'{source}:{case}:safe-seeds', cond['safe'], expected_safe)
            check(f'{source}:{case}:no-duplicate', cond['duplicate'], 0)
            check(f'{source}:{case}:no-stale', cond['stale'], 0)
        summary['sources'][source] = dict(
            runs=len(runs), tasks=tasks, policies=aggregate,
            clear_conditions={case: dict(seeds=cond['seeds'], safe_seeds=cond['safe'],
                                         terminals=dict(cond['terminals']),
                                         rows=dict(cond['rows']))
                              for case, cond in conditions.items()},
            clear_safe=aggregate['clear']['safe'],
            clear_total=aggregate['clear']['tasks'],
            clear_wilson=wilson(aggregate['clear']['safe'], aggregate['clear']['tasks']),
            seed_aggregates=seed_aggregates)
        summary['total_tasks'] += tasks

    check('total-tasks', summary['total_tasks'], len(sources) * 400)
    total = len(CHECKS)
    passed = sum(1 for item in CHECKS if item['ok'])
    failed = [item for item in CHECKS if not item['ok']]
    summary.update(checks_total=total, checks_passed=passed, failed=failed,
                   status='pass' if not failed else 'fail')
    save(out / 'summary.json', summary)
    save(out / 'analysis1/verification.json', dict(checks=CHECKS, checks_total=total,
         checks_passed=passed, failed=failed, status=summary['status']))
    save(out / 'freeze.json', dict(
        schema='r4_10seed_freeze_v1', sources={source: [str(run) for run in runs]
                                               for source, runs in sources.items()},
        seeds=list(range(10)), policies=POLICIES, cases=CASES,
        run_hashes={run.relative_to(ROOT).as_posix(): sha(run / 'completion.json')
                    for runs in sources.values() for run in runs},
        created='2026-10-21'))

    lines = [f'# {args.title}', '',
             f'8 conditions x 5 policies x 10 seeds = 400 tasks per source; '
             f'{len(sources)} sources, {summary["total_tasks"]} tasks.', '',
             '## Policy summary (400 tasks per source)', '',
             '| source | policy | safe | complete | duplicates | stale | pause |',
             '|---|---|---:|---:|---:|---:|---:|']
    for source, body in summary['sources'].items():
        for policy in POLICIES:
            entry = body['policies'][policy]
            lines.append(f"| {source} | {policy} | {entry['safe']} | {entry['complete']} | "
                         f"{entry['duplicate']} | {entry['stale']} | {entry['pause']} |")
    lines += ['', '## CLEAR by condition (10 seeds)', '',
              '| source | condition | safe seeds | terminals | rows |', '|---|---|---:|---|---|']
    for source, body in summary['sources'].items():
        for case, cond in body['clear_conditions'].items():
            lines.append(f"| {source} | {case} | {cond['safe_seeds']}/10 | "
                         f"{cond['terminals']} | {cond['rows']} |")
    lines += ['', '## CLEAR safe completion', '',
              '| source | safe/total | Wilson 95% |', '|---|---:|---|']
    for source, body in summary['sources'].items():
        lines.append(f"| {source} | {body['clear_safe']}/{body['clear_total']} | "
                     f"{body['clear_wilson']} |")
    lines += ['', f"Verification: {passed}/{total}; status: {summary['status']}.", '']
    (out / 'table.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(dict(status=summary['status'], checks_total=total,
                          checks_passed=passed, total_tasks=summary['total_tasks']),
                     ensure_ascii=False))
    sys.exit(0 if not failed else 1)


if __name__ == '__main__':
    main()
