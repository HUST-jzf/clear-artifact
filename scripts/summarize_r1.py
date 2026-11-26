"""Summarize R1 cells into a boundary table (descriptive; no inference)."""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']


def flag(task):
    return ('C' if task['terminal'] == 'complete' else 'P') + \
           ('s' if task['safe'] else 'u') + \
           ('D' if task['duplicate'] else '-') + \
           (f"X{task['stale_new']}" if task['stale_new'] else '-')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('verification')
    parser.add_argument('--output')
    args = parser.parse_args()
    data = json.loads(Path(args.verification).read_text(encoding='utf-8'))
    cells = data['cells']
    rows = []
    for case_id in sorted(cells):
        policies = cells[case_id]['policies']
        row = dict(case=case_id, factors=cells[case_id]['factors'],
                   clear=flag(policies['clear']), idem=flag(policies['idem_retry']),
                   query=flag(policies['query_retry']), reauth=flag(policies['reauth_retry']),
                   pause=flag(policies['pause']))
        row['clear_only_safe_complete'] = (
            policies['clear']['safe'] and policies['clear']['terminal'] == 'complete' and
            not any(policies[p]['safe'] and policies[p]['terminal'] == 'complete'
                    for p in ['idem_retry', 'query_retry', 'reauth_retry']))
        row['clear_safe_others_unsafe'] = (
            policies['clear']['safe'] and policies['clear']['terminal'] == 'complete' and
            all(not (policies[p]['safe'] and policies[p]['terminal'] == 'complete')
                for p in ['idem_retry', 'query_retry', 'reauth_retry']))
        rows.append(row)
    counts = Counter()
    for row in rows:
        counts['clear_only_safe_complete'] += row['clear_only_safe_complete']
        counts['clear_safe_others_unsafe'] += row['clear_safe_others_unsafe']
    by_idem = defaultdict(Counter)
    for row in rows:
        key = str(row['factors']['idempotency'])
        by_idem[key]['cells'] += 1
        by_idem[key]['clear_only'] += row['clear_only_safe_complete']
    text = []
    text.append('| case | CLEAR | idem | query | reauth | pause |')
    text.append('|---|---|---|---|---|---|')
    for row in rows:
        text.append(f"| {row['case']} | {row['clear']} | {row['idem']} | {row['query']} | "
                    f"{row['reauth']} | {row['pause']} |")
    summary = dict(counts=counts, by_idempotency={k: dict(v) for k, v in by_idem.items()},
                   rows=rows)
    if args.output:
        Path(args.output).write_text('\n'.join(text) + '\n', encoding='utf-8')
    print(json.dumps(dict(counts=counts, by_idempotency=summary['by_idempotency']),
                     ensure_ascii=False))
    print('\n'.join(text))


if __name__ == '__main__':
    main()
