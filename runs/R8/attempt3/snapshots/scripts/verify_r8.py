"""Independent R8 ablation verifier."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FULL = {
    'normal': ('complete', 1), 'fail_before': ('complete', 1),
    'lost_return': ('complete', 1), 'late_commit': ('complete', 1),
    'revoke': ('pause', 0), 'manifest_change': ('pause', 0),
    'query_unavailable': ('pause', 1), 'late_closure': ('complete', 1),
    'atomic_revoke': ('pause', 0),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(run):
    run = Path(run)
    checks = []

    def check(name, ok, detail=None):
        checks.append(dict(name=name, ok=bool(ok), detail=detail))

    freeze = json.loads((run / 'freeze.json').read_text(encoding='utf-8'))
    install = json.loads((run / 'installation.json').read_text(encoding='utf-8'))
    for name, expected in freeze['files'].items():
        check('freeze:' + name, (run / 'snapshots' / name).exists() and
              sha(run / 'snapshots' / name) == expected)
    check('version:clear-assurance',
          install['versions'].get('clear-assurance') == '2.0.0', install['versions'])
    completion = json.loads((run / 'completion.json').read_text(encoding='utf-8'))
    check('no-run-failures', not completion.get('failures'), completion.get('failures'))
    check('task-count', len(completion['tasks']) == 450, len(completion['tasks']))

    tasks = completion['tasks']
    cells = {}
    for case in freeze['cases']:
        for variant in freeze['variants']:
            rows = [t for t in tasks if t['case'] == case['id'] and t['variant'] == variant]
            cells[f"{case['id']}:{variant}"] = dict(
                tasks=len(rows), safe=sum(t['safe'] for t in rows),
                complete=sum(t['terminal'] == 'complete' for t in rows),
                duplicate=sum(t['duplicate'] for t in rows),
                stale_permit=sum(t['stale_permit'] > 0 for t in rows),
                stale_manifest=sum(t['stale_manifest'] > 0 for t in rows),
                false_complete=sum(t['false_complete'] for t in rows),
                pause=sum(t['terminal'] == 'pause' for t in rows))
    for case, (terminal, expected_rows) in FULL.items():
        cell = cells[f'{case}:full']
        check('full-terminal:' + case, cell['complete' if terminal == 'complete' else 'pause'] == 10,
              cell)
        rows = [t for t in tasks if t['case'] == case and t['variant'] == 'full']
        check('full-rows:' + case, all(t['rows'] == expected_rows for t in rows),
              sorted({t['rows'] for t in rows}))
    full = [t for t in tasks if t['variant'] == 'full']
    check('full-no-duplicate', not any(t['duplicate'] for t in full))
    check('full-no-stale-permit', not any(t['stale_permit'] for t in full))
    check('full-no-stale-manifest', not any(t['stale_manifest'] for t in full))
    check('full-no-false-complete', not any(t['false_complete'] for t in full))
    check('full-safe-count', sum(t['safe'] for t in full) == 50, sum(t['safe'] for t in full))

    def counter(variant, predicate, minimum):
        rows = [t for t in tasks if t['variant'] == variant]
        return sum(1 for t in rows if predicate(t)) >= minimum

    check('no_closure-duplicate', counter('no_closure', lambda t: t['duplicate'], 10))
    check('no_query-duplicate', counter('no_query', lambda t: t['duplicate'], 10))
    check('no_version-stale-manifest',
          counter('no_version', lambda t: t['stale_manifest'] > 0, 10))
    check('no_atomic-stale-permit',
          counter('no_atomic', lambda t: t['stale_permit'] > 0, 10))
    check('no-false-complete', not any(t['false_complete'] for t in tasks))

    aggregate = {}
    for variant in freeze['variants']:
        rows = [t for t in tasks if t['variant'] == variant]
        aggregate[variant] = dict(tasks=len(rows), safe=sum(t['safe'] for t in rows),
                                  complete=sum(t['terminal'] == 'complete' for t in rows),
                                  duplicates=sum(t['duplicate'] for t in rows),
                                  pause=sum(t['terminal'] == 'pause' for t in rows),
                                  stale_permit=sum(t['stale_permit'] > 0 for t in rows),
                                  stale_manifest=sum(t['stale_manifest'] > 0 for t in rows),
                                  false_complete=sum(t['false_complete'] for t in rows))
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
