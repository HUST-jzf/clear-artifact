"""Independent R11 verifier: real subprocess crash and restart."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEAR_REQUIRED = {
    'crash_after_commit': ('complete', 1),
    'crash_before_commit': ('pause', 0),
    'crash_after_commit_revoke': ('complete', 1),
    'crash_before_commit_revoke': ('pause', 0),
    'crash_after_commit_no_query': ('pause', 1),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(run):
    run = Path(run)
    checks = []

    def check(name, ok, detail=None):
        checks.append(dict(name=name, ok=bool(ok), detail=detail))

    freeze = json.loads((run / 'freeze.json').read_text(encoding='utf-8'))
    for name, expected in freeze['files'].items():
        check('freeze:' + name, (run / 'snapshots' / name).exists() and
              sha(run / 'snapshots' / name) == expected)
    completion = json.loads((run / 'completion.json').read_text(encoding='utf-8'))
    seeds = freeze['seeds']
    count = len(seeds)
    check('no-run-failures', not completion.get('failures'), completion.get('failures'))
    check('task-count', len(completion['tasks']) == 5 * 5 * count, len(completion['tasks']))

    cells = {}
    for case in freeze['cases']:
        for policy in freeze['policies']:
            for seed in freeze['seeds']:
                directory = run / f"S{seed}_{case['id']}_{policy}"
                result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
                native = json.loads((directory / 'native.json').read_text(encoding='utf-8'))
                effects = []
                if (directory / 'effects.sqlite').exists():
                    with sqlite3.connect(directory / 'effects.sqlite') as db:
                        effects = db.execute('select attempt,origin,allowed from effects '
                                             'order by id').fetchall()
                rows = len(effects)
                stale = sum(1 for attempt, origin, allowed in effects
                            if attempt > 1 and not allowed)
                duplicate = rows > 1
                false_complete = result['terminal'] == 'complete' and rows == 0
                key = f"{case['id']}:{policy}"
                cell = cells.setdefault(key, dict(case=case['id'], policy=policy, seeds={}))
                cell['seeds'][seed] = dict(terminal=result['terminal'], rows=rows,
                                           duplicate=duplicate, stale=stale,
                                           false_complete=false_complete,
                                           crashes=len(native.get('crashed_markers', [])),
                                           initial=native['initial_observations'])
                if policy == 'clear':
                    check('clear-no-duplicate:' + key + f':S{seed}', not duplicate, rows)
                    check('clear-no-stale:' + key + f':S{seed}', not stale, stale)
                    check('clear-no-false-complete:' + key + f':S{seed}', not false_complete, rows)
                    expected = CLEAR_REQUIRED[case['id']]
                    if expected[0] is not None:
                        check('clear-terminal:' + key + f':S{seed}',
                              result['terminal'] == expected[0], result['terminal'])
                    if expected[1] is not None:
                        check('clear-rows:' + key + f':S{seed}', rows == expected[1], rows)
                check('crashed:' + key + f':S{seed}',
                      len(native.get('crashed_markers', [])) == 1,
                      native.get('crashed_markers'))
    check('clear-tasks', sum(1 for cell in cells.values() if cell['policy'] == 'clear') * count,
          5 * count)

    def seed_values(case, policy, field):
        cell = cells[f'{case}:{policy}']
        return [item[field] for item in cell['seeds'].values()]

    check('after-commit-query-safe',
          sum(1 for value in seed_values('crash_after_commit', 'query_retry', 'terminal')
              if value == 'complete'), count)
    check('after-commit-idem-duplicate',
          sum(seed_values('crash_after_commit', 'idem_retry', 'duplicate')), count)
    check('after-commit-reauth-duplicate',
          sum(seed_values('crash_after_commit', 'reauth_retry', 'duplicate')), count)
    check('before-commit-idem-safe',
          sum(1 for value in seed_values('crash_before_commit', 'idem_retry', 'terminal')
              if value == 'complete'), count)
    check('before-commit-clear-pause',
          sum(1 for value in seed_values('crash_before_commit', 'clear', 'terminal')
              if value == 'pause'), count)
    check('before-revoke-clear-pause',
          sum(1 for value in seed_values('crash_before_commit_revoke', 'clear', 'terminal')
              if value == 'pause'), count)
    check('no-query-clear-pause',
          sum(1 for value in seed_values('crash_after_commit_no_query', 'clear', 'terminal')
              if value == 'pause'), count)
    check('no-query-query-pause',
          sum(1 for value in seed_values('crash_after_commit_no_query', 'query_retry', 'terminal')
              if value == 'pause'), count)
    check('after-revoke-idem-duplicate',
          sum(seed_values('crash_after_commit_revoke', 'idem_retry', 'duplicate')), count)
    check('after-revoke-idem-stale',
          sum(seed_values('crash_after_commit_revoke', 'idem_retry', 'stale')), count)
    check('before-revoke-idem-stale',
          sum(seed_values('crash_before_commit_revoke', 'idem_retry', 'stale')), count)
    check('before-revoke-query-stale',
          sum(seed_values('crash_before_commit_revoke', 'query_retry', 'stale')), count)
    check('before-revoke-reauth-clean',
          sum(1 for item in cells['crash_before_commit_revoke:reauth_retry']['seeds'].values()
              if item['terminal'] == 'complete' and item['rows'] == 1 and not item['stale']),
          count)
    aggregate = {}
    for key, cell in cells.items():
        aggregate[key] = dict(
            safe=sum(1 for item in cell['seeds'].values()
                     if item['terminal'] == 'complete' and item['rows'] <= 1
                     and not item['duplicate'] and not item['stale'] and not item['false_complete']),
            complete=sum(1 for item in cell['seeds'].values() if item['terminal'] == 'complete'),
            duplicate=sum(1 for item in cell['seeds'].values() if item['duplicate']),
            stale=sum(1 for item in cell['seeds'].values() if item['stale'] > 0),
            false_complete=sum(1 for item in cell['seeds'].values() if item['false_complete']))
    return dict(checks=checks, cells=cells, aggregate=aggregate,
                failed=[item for item in checks if not item['ok']])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('--output')
    args = parser.parse_args()
    result = verify(args.run)
    result.update(checks_total=len(result['checks']),
                  checks_passed=sum(1 for item in result['checks'] if item['ok']))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + '\n', encoding='utf-8')
    print(json.dumps(dict(checks_total=result['checks_total'],
                          checks_passed=result['checks_passed'],
                          aggregate=result['aggregate'], failed=result['failed'][:10]),
                     ensure_ascii=False))
    sys.exit(0 if not result['failed'] else 1)


if __name__ == '__main__':
    main()
