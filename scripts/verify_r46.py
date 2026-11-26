"""R46 verifier: rebuild every cell from the workflow SQLite files.

Effects, intents, duplicates and merges are read again from each workflow's
database and compared with `completion.json` before the acceptance matrix is
checked.
"""
import argparse
import json
import sqlite3
from pathlib import Path

FAULTS = ['lost_return', 'late_commit']
VARIANTS = ['exact', 'paraphrase']


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def observe(path):
    db = sqlite3.connect(path)
    try:
        rows = db.execute("select op, intent, count(*) from effects "
                          "where status='committed' group by op, intent").fetchall()
        deduplicated = db.execute('select count(*) from dedup_hits').fetchone()[0]
    finally:
        db.close()
    ops = {}
    for op, intent, count in rows:
        entry = ops.setdefault(op, dict(effects=0, intents=[]))
        entry['effects'] += count
        entry['intents'].append(intent)
    effects = sum(entry['effects'] for entry in ops.values())
    intents = [intent for entry in ops.values() for intent in entry['intents']]
    return dict(ops=ops, effects=effects, intents=intents,
                deduplicated=int(deduplicated))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--out')
    args = parser.parse_args()
    run = Path(args.run)
    freeze = load(run / 'freeze.json')
    completion = load(run / 'completion.json')
    seeds = set(freeze['seeds'])
    tasks = completion['tasks']
    checks, passed, mismatches = [], [], []

    def check(name, actual, expected):
        checks.append(name)
        if actual == expected:
            passed.append(name)
        else:
            print(json.dumps({'check': name, 'actual': actual, 'expected': expected}))

    check('meta.failures', completion['failures'], [])
    expected = sum(len(regime['policies']) * 5 * len(seeds)
                   for regime in freeze['regimes'].values())
    check('meta.tasks', len(tasks), expected)

    for task in tasks:
        path = run / f"{task['regime']}_{task['policy']}" / 'private' \
            / (task['workflow'] + '.sqlite')
        metric = observe(path)
        task['observed'] = metric
        if metric['effects'] != task['effects'] or sorted(metric['intents']) != \
                sorted(task['intents']):
            mismatches.append(dict(workflow=task['workflow'],
                                   recorded=dict(effects=task['effects'],
                                                 intents=task['intents']),
                                   observed=dict(effects=metric['effects'],
                                                 intents=metric['intents'])))
    check('sqlite.recompute-mismatches', mismatches, [])

    def select(regime, policy, cell):
        return [task for task in tasks
                if task['regime'] == regime and task['policy'] == policy
                and task['cell'] == cell]

    def cells(regime, policy):
        return sorted({task['cell'] for task in tasks
                       if task['regime'] == regime and task['policy'] == policy})

    for regime, info in freeze['regimes'].items():
        for policy in info['policies']:
            for cell in cells(regime, policy):
                check(f'count.{regime}.{policy}.{cell}',
                      len(select(regime, policy, cell)), len(seeds))

    loss = 'A_lost_return_exact'
    para = 'A_lost_return_paraphrase'
    check('fixed.versioned.exact.effects',
          sorted({task['effects'] for task in select('fixed', 'dedup_versioned', loss)}), [1])
    check('fixed.versioned.exact.safe-complete',
          sum(1 for task in select('fixed', 'dedup_versioned', loss)
              if task['safe_complete']), len(seeds))
    check('fresh.fresh.exact.duplicates',
          sum(1 for task in select('fresh', 'dedup_fresh', loss) if task['duplicate']),
          len(seeds))
    check('fresh.fresh.exact.effects',
          sorted({task['effects'] for task in select('fresh', 'dedup_fresh', loss)}), [2])

    check('fixed.versioned.paraphrase.false-split',
          sum(1 for task in select('fixed', 'dedup_versioned', para)
              if task['false_split']), len(seeds))
    check('fixed.semantic.paraphrase.effects',
          sorted({task['effects'] for task in select('fixed', 'semantic_dedup', para)}), [1])
    for regime in ('fixed', 'fresh', 'none'):
        check(f'{regime}.semantic.content-merge',
              sum(1 for task in select(regime, 'semantic_dedup', 'B')
                  if task['false_merge']), len(seeds))
    check('fixed.versioned.new-intent.separated',
          sum(1 for task in select('fixed', 'dedup_versioned', 'B')
              if task['correct']), len(seeds))
    check('fixed.versioned.new-intent.effects',
          sorted({task['effects'] for task in select('fixed', 'dedup_versioned', 'B')}),
          [2])

    for cell in cells('fixed', 'clear_evidence'):
        rows = select('fixed', 'clear_evidence', cell)
        check(f'clear.no-duplicate.{cell}',
              sum(1 for task in rows if task['duplicate'] or task['false_split']), 0)
    for regime in ('fixed', 'fresh', 'none'):
        for cell in cells(regime, 'clear_evidence'):
            rows = select(regime, 'clear_evidence', cell)
            check(f'clear.no-merge.{regime}.{cell}',
                  sum(1 for task in rows if task['false_merge']), 0)
    check('clear.paraphrase.lost.pauses',
          sum(1 for task in select('fixed', 'clear_evidence', para) if task['paused']),
          len(seeds))
    check('clear.paraphrase.lost.effects',
          sorted({task['effects'] for task in select('fixed', 'clear_evidence', para)}), [1])
    check('clear.exact.both-faults.complete',
          sum(1 for cell in ('A_lost_return_exact', 'A_late_commit_exact')
              for task in select('fixed', 'clear_evidence', cell)
              if task['safe_complete']), 2 * len(seeds))
    check('clear.new-intent.refuses',
          sum(1 for task in select('fixed', 'clear_evidence', 'B') if task['paused']),
          len(seeds))
    check('clear.new-intent.effects',
          sorted({task['effects'] for task in select('fixed', 'clear_evidence', 'B')}), [1])

    silent = []
    for regime, info in freeze['regimes'].items():
        for policy in info['policies']:
            if policy not in ('dedup_versioned', 'dedup_fresh', 'semantic_dedup'):
                continue
            a_cells = [cell for cell in cells(regime, policy) if cell.startswith('A_')]
            no_duplicate = all(task['effects'] == 1
                               for cell in a_cells
                               for task in select(regime, policy, cell))
            no_merge = all(task['effects'] == 2
                           for task in select(regime, policy, 'B'))
            if no_duplicate and no_merge:
                silent.append(f'{regime}/{policy}')
    check('keyed.no-free-lunch', silent, [])
    op_keyed = []
    for regime, info in freeze['regimes'].items():
        for policy in ('clear_fenced', 'verify_retry', 'clear_evidence'):
            if policy not in info['policies']:
                continue
            a_cells = [cell for cell in cells(regime, policy) if cell.startswith('A_')]
            no_split = all(not task['false_split'] and not task['duplicate']
                           for cell in a_cells
                           for task in select(regime, policy, cell))
            no_merge = all(not task['false_merge']
                           for task in select(regime, policy, 'B'))
            if no_split and no_merge:
                op_keyed.append(f'{regime}/{policy}')
    check('op-keyed.clean', sorted(op_keyed),
          ['fixed/clear_evidence', 'fixed/clear_fenced', 'fresh/clear_evidence',
           'fresh/clear_fenced', 'none/clear_evidence', 'none/clear_fenced'])

    table = {}
    for regime, info in freeze['regimes'].items():
        for policy in info['policies']:
            entry = {}
            for cell in cells(regime, policy):
                rows = select(regime, policy, cell)
                entry[cell] = dict(
                    effects=sorted({task['effects'] for task in rows}),
                    duplicate=sum(1 for task in rows if task['duplicate']),
                    false_split=sum(1 for task in rows if task['false_split']),
                    false_merge=sum(1 for task in rows if task['false_merge']),
                    paused=sum(1 for task in rows if task['paused']),
                    requests=sum(task['requests'] for task in rows) / max(1, len(rows)))
            table[f'{regime}/{policy}'] = entry

    summary = dict(checks=len(checks), passed=len(passed),
                   status='pass' if len(passed) == len(checks) else 'fail',
                   mismatches=len(mismatches), cells=table)
    out = Path(args.out) if args.out else run / 'verification.json'
    out.write_text(json.dumps(dict(summary, failed=[c for c in checks if c not in passed]),
                              ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('status', 'checks', 'passed', 'mismatches')}))
    if summary['status'] != 'pass':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
