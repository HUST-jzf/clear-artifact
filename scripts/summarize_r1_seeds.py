"""Aggregate R1 ten-seed runs; Wilson intervals are descriptive, not a substitute for a frozen analysis."""
import argparse
import json
import math
from collections import Counter
from pathlib import Path

SOURCES = {
    'MCP': ['runs/R1/attempt2'] + [f'runs/R1/seed{i}' for i in range(1, 10)],
    'AnyIO': ['runs/R1_anyio/attempt1'] + [f'runs/R1_anyio/seed{i}' for i in range(1, 10)],
    'LangChain': ['runs/R1_langchain/attempt2'] + [f'runs/R1_langchain/seed{i}' for i in range(1, 10)],
}
POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']


def wilson(k, n, z=1.959963984540054):
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [max(0.0, center - half), min(1.0, center + half)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output')
    args = parser.parse_args()
    report = dict(sources={}, seeds=10)
    for source, paths in SOURCES.items():
        totals = {p: Counter() for p in POLICIES}
        cell_clear = Counter()
        seed_presence = []
        for path in paths:
            data = json.loads((Path(path) / 'analysis1/verification.json').read_text(encoding='utf-8'))
            seed_presence.append(dict(path=path, tasks=sum(v['tasks'] for v in data['aggregate'].values())))
            for policy in POLICIES:
                totals[policy].update(data['aggregate'][policy])
            for case, cell in data['cells'].items():
                if cell['policies']['clear']['safe'] and cell['policies']['clear']['terminal'] == 'complete':
                    cell_clear[case] += 1
        result = {}
        for policy in POLICIES:
            item = dict(totals[policy])
            n = item['tasks']
            for metric in ['safe', 'complete', 'duplicates', 'stale_new']:
                item[metric + '_rate'] = item[metric] / n if n else 0.0
                item[metric + '_ci95'] = wilson(item[metric], n)
            result[policy] = item
        report['sources'][source] = dict(
            seeds=seed_presence, policies=result,
            clear_cell_counts=dict(cell_clear),
            stable_cells_10=sum(1 for value in cell_clear.values() if value == 10),
            never_cells=sum(1 for value in cell_clear.values() if value == 0),
            variable_cells={case: value for case, value in cell_clear.items() if 0 < value < 10})
    text = []
    text.append('| source | policy | safe | 95% CI | duplicates | duplicate rate | stale controller writes |')
    text.append('|---|---|---:|---|---:|---:|---:|')
    for source, item in report['sources'].items():
        for policy in POLICIES:
            value = item['policies'][policy]
            low, high = value['safe_ci95']
            text.append(f"| {source} | {policy} | {value['safe']}/{value['tasks']} | "
                        f"[{low:.3f}, {high:.3f}] | {value['duplicates']} | "
                        f"{value['duplicates_rate']:.3f} | {value['stale_new']} |")
    if args.output:
        Path(args.output).write_text('\n'.join(text) + '\n', encoding='utf-8')
        Path(args.output).with_suffix('.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({source: dict(
        clear=dict(safe=item['policies']['clear']['safe'], tasks=item['policies']['clear']['tasks'],
                   ci=item['policies']['clear']['safe_ci95'], duplicates=item['policies']['clear']['duplicates'],
                   stale=item['policies']['clear']['stale_new']),
        stable_cells_10=item['stable_cells_10'], variable_cells=item['variable_cells'])
        for source, item in report['sources'].items()}, ensure_ascii=False))
    print('\n'.join(text))


if __name__ == '__main__':
    main()
