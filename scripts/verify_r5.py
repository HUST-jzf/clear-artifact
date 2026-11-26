"""Independent R5 verifier: atomic admission vs single-mechanism policies."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
    check('no-run-failures', not completion.get('failures'), completion.get('failures'))

    cells, tasks = {}, []
    for cell in freeze['cells']:
        change, idem = cell['change'], cell['idempotency']
        for policy in freeze['policies']:
            key = f'G{change}I{idem}:{policy}'
            entry = cells.setdefault(key, dict(change=change, idempotency=idem,
                                               policy=policy, seeds={}))
            for seed in freeze['seeds']:
                label = f'{key}/S{seed}'
                directory = run / f'S{seed}_G{change}I{idem}_{policy}'
                if not (directory / 'result.json').exists():
                    check('missing:' + label, False)
                    continue
                result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
                if policy == 'pause':
                    expected_rows = 0
                elif policy == 'clear':
                    expected_rows = 1 if change == 'none' else 0
                else:
                    expected_rows = 1 if idem == 1 else 2
                if change == 'none' or policy in ('clear', 'reauth_retry', 'pause'):
                    expected_stale = 0
                else:
                    expected_stale = 1 if idem == 1 else 2
                expected_aborted = 2 if (policy == 'clear' and change == 'revoke') else 0
                check('rows:' + label, result['rows'] == expected_rows,
                      dict(actual=result['rows'], expected=expected_rows))
                check('duplicate:' + label, result['duplicate'] is (expected_rows > 1),
                      result['duplicate'])
                check('stale:' + label, result['stale_new'] == expected_stale,
                      dict(actual=result['stale_new'], expected=expected_stale))
                check('aborted:' + label, result['aborted'] == expected_aborted,
                      dict(actual=result['aborted'], expected=expected_aborted))
                check('errors:' + label, not result['errors'], result['errors'])
                safe = result['rows'] == 1 and result['stale_new'] == 0
                task = dict(case=result['case'], policy=policy, seed=seed,
                            rows=result['rows'], duplicate=result['duplicate'],
                            stale_new=result['stale_new'], aborted=result['aborted'],
                            safe=safe)
                tasks.append(task)
                entry['seeds'][seed] = task
    aggregate = dict(tasks=len(tasks),
                     safe=sum(t['safe'] for t in tasks),
                     complete=sum(t['rows'] == 1 for t in tasks),
                     duplicates=sum(t['duplicate'] for t in tasks),
                     stale=sum(t['stale_new'] > 0 for t in tasks),
                     aborted=sum(t['aborted'] for t in tasks))
    check('task-count', len(tasks) == 400, len(tasks))
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
                          aggregate=result['aggregate'],
                          failed=result['failed'][:10]), ensure_ascii=False))
    sys.exit(0 if not result['failed'] else 1)


if __name__ == '__main__':
    main()
