"""Independent R13 verifier for one source."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIELDS = ('adapter', 'version', 'python', 'framework', 'worker_sha256',
                 'host_sha256', 'observer_sha256')
EXPECTED_MUTATIONS = {
    ('manifest_change', 'clear'): 1,
    ('manifest_change', 'idem_retry'): 1,
    ('manifest_change', 'query_retry'): 1,
    ('manifest_change', 'reauth_retry'): 1,
    ('manifest_change', 'pause'): 1,
    ('revoke_before_recovery', 'clear'): 1,
    ('revoke_before_recovery', 'idem_retry'): 1,
    ('revoke_before_recovery', 'query_retry'): 1,
    ('revoke_before_recovery', 'reauth_retry'): 1,
    ('revoke_before_recovery', 'pause'): 1,
    ('revoke_after_query', 'clear'): 1,
    ('revoke_after_query', 'idem_retry'): 0,
    ('revoke_after_query', 'query_retry'): 1,
    ('revoke_after_query', 'reauth_retry'): 0,
    ('revoke_after_query', 'pause'): 0,
    ('revoke_during_requalification', 'clear'): 2,
    ('revoke_during_requalification', 'idem_retry'): 0,
    ('revoke_during_requalification', 'query_retry'): 0,
    ('revoke_during_requalification', 'reauth_retry'): 0,
    ('revoke_during_requalification', 'pause'): 0,
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(run, source):
    run = Path(run)
    checks = []

    def check(name, ok, detail=None):
        checks.append(dict(name=name, ok=bool(ok), detail=detail))

    freeze = json.loads((run / 'freeze.json').read_text(encoding='utf-8'))
    install = json.loads((run / 'installation.json').read_text(encoding='utf-8'))
    for name, expected in freeze['files'].items():
        check('freeze:' + name, (run / 'snapshots' / name).exists() and
              sha(run / 'snapshots' / name) == expected)
    expected_versions = {'anyio': {'anyio': '4.12.1'},
                         'langchain': {'langchain-core': '1.0.0',
                                       'anyio': '4.15.1'}}[source]
    for name, expected in expected_versions.items():
        check('version:' + name, install['versions'].get(name) == expected, install['versions'])
    check('version:clear-assurance',
          install['versions'].get('clear-assurance') == '2.0.0', install['versions'])
    completion = json.loads((run / 'completion.json').read_text(encoding='utf-8'))
    check('no-run-failures', not completion.get('failures'), completion.get('failures'))
    expected_tasks = len(freeze['modes']) * len(freeze['seeds']) * len(freeze['policies'])
    check('task-count', len(completion['tasks']) == expected_tasks, len(completion['tasks']))

    cells, tasks = {}, []
    for case in freeze['cases']:
        for policy in freeze['policies']:
            key = f"{case['mode']}:{policy}"
            entry = cells.setdefault(key, dict(mode=case['mode'], policy=policy, seeds={}))
            label = f"{key}/S{case['seed']}"
            directory = run / f"S{case['seed']}_{case['mode']}_{policy}"
            if not (directory / 'result.json').exists():
                check('missing:' + label, False)
                continue
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
            events = result.get('events', [])
            qualification = [event for event in events if event['action'] == 'qualify']
            requalified = any(event['body'].get('valid') is True for event in qualification)
            qualify_rejected = any(event['body'].get('valid') is not True
                                   for event in qualification)
            atomic_rejected = any(event['body'].get('state') == 'stale_qualification'
                                  for event in events)
            origin_manifest, final_manifest = native['origin']['manifest'], native['final_manifest']
            changed = sorted(key for key in SOURCE_FIELDS
                             if origin_manifest.get(key) != final_manifest.get(key))
            unqualified_write = (result['terminal'] == 'complete' and rows >= 1
                                 and bool(changed) and not requalified)
            mutations = len(result.get('mutations', []))
            task = dict(mode=case['mode'], seed=case['seed'], policy=policy,
                        terminal=result['terminal'], reason=result.get('reason'),
                        rows=rows, duplicate=duplicate, stale_new=stale,
                        pause_with_effect=result['terminal'] == 'pause' and rows > 0,
                        changed=changed, requalified=requalified,
                        qualify_rejected=qualify_rejected, atomic_rejected=atomic_rejected,
                        unqualified_write=unqualified_write, mutations=mutations)
            task['safe'] = (task['terminal'] == 'complete' and rows == 1 and stale == 0
                            and not unqualified_write)
            tasks.append(task)
            entry['seeds'][case['seed']] = task

            check('mutations:' + label, mutations == EXPECTED_MUTATIONS[(case['mode'], policy)],
                  mutations)
            check('clear-no-duplicate:' + label, policy != 'clear' or not duplicate, rows)
            check('clear-no-stale:' + label, policy != 'clear' or stale == 0, stale)
            check('stale-write-recorded:' + label, stale <= 1, stale)
            if policy == 'clear':
                check('clear-pause:' + label, result['terminal'] == 'pause', result['terminal'])
                check('clear-no-effect:' + label, rows == 0, rows)
                check('clear-no-unqualified:' + label, not unqualified_write, changed)
    check('transient-cells', len(tasks) == expected_tasks, len(tasks))

    def values(mode, policy, field):
        return [item[field] for item in cells[f'{mode}:{policy}']['seeds'].values()]

    seeds = len(freeze['seeds'])
    check('manifest-clear-pause',
          sum(1 for item in values('manifest_change', 'clear', 'terminal') if item == 'pause'),
          seeds)
    check('manifest-retry-unqualified',
          sum(values('manifest_change', 'idem_retry', 'unqualified_write')) +
          sum(values('manifest_change', 'query_retry', 'unqualified_write')) +
          sum(values('manifest_change', 'reauth_retry', 'unqualified_write')), 3 * seeds)
    check('revoke-before-idem-stale',
          sum(values('revoke_before_recovery', 'idem_retry', 'stale_new')), seeds)
    check('revoke-before-query-stale',
          sum(values('revoke_before_recovery', 'query_retry', 'stale_new')), seeds)
    check('revoke-before-reauth-clean',
          sum(1 for item in cells['revoke_before_recovery:reauth_retry']['seeds'].values()
              if item['terminal'] == 'complete' and item['rows'] == 1
              and item['stale_new'] == 0), seeds)
    check('revoke-after-query-stale',
          sum(values('revoke_after_query', 'query_retry', 'stale_new')), seeds)
    check('revoke-after-query-idem-clean',
          sum(1 for item in cells['revoke_after_query:idem_retry']['seeds'].values()
              if item['terminal'] == 'complete' and item['stale_new'] == 0), seeds)
    check('requalification-atomic-rejected',
          sum(1 for item in cells['revoke_during_requalification:clear']['seeds'].values()
              if item['atomic_rejected'] and item['terminal'] == 'pause'
              and item['rows'] == 0), seeds)

    aggregate = dict(tasks=len(tasks),
                     safe=sum(t['safe'] for t in tasks),
                     complete=sum(t['terminal'] == 'complete' for t in tasks),
                     duplicates=sum(t['duplicate'] for t in tasks),
                     stale=sum(t['stale_new'] for t in tasks),
                     pause=sum(t['terminal'] == 'pause' for t in tasks),
                     pause_with_effect=sum(t['pause_with_effect'] for t in tasks),
                     unqualified_write=sum(t['unqualified_write'] for t in tasks),
                     atomic_rejected=sum(t['atomic_rejected'] for t in tasks))
    return dict(checks=checks, cells=cells, aggregate=aggregate,
                failed=[item for item in checks if not item['ok']])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('--source', required=True, choices=['anyio', 'langchain'])
    parser.add_argument('--output')
    args = parser.parse_args()
    result = verify(args.run, args.source)
    result.update(source=args.source, checks_total=len(result['checks']),
                  checks_passed=sum(1 for item in result['checks'] if item['ok']))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + '\n', encoding='utf-8')
    print(json.dumps(dict(source=args.source, checks_total=result['checks_total'],
                          checks_passed=result['checks_passed'],
                          aggregate=result['aggregate'],
                          failed=result['failed'][:10]), ensure_ascii=False))
    sys.exit(0 if not result['failed'] else 1)


if __name__ == '__main__':
    main()
