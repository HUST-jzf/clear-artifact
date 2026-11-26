"""Independent R1 verifier: stdlib only; no CLEAR, MCP or experiment imports."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve_recorded_path(record):
    """Use the shipped content-addressed mirror when the original environment is absent."""
    path = Path(record['path'])
    if path.exists():
        return path
    mirror = ROOT / 'sources/_installation_mirror' / record['sha256']
    return mirror if mirror.exists() else path


def verify(run):
    run = Path(run)
    checks = []

    def check(name, ok, detail=None):
        checks.append(dict(name=name, ok=bool(ok), detail=detail))

    freeze = json.loads((run / 'freeze.json').read_text(encoding='utf-8'))
    install = json.loads((run / 'installation.json').read_text(encoding='utf-8'))
    for name, expected in freeze['files'].items():
        snapshot = run / 'snapshots' / name
        check('freeze:' + name, snapshot.exists() and sha(snapshot) == expected)
    check('package-version', install['versions'].get('clear-assurance') == '2.0.0',
          install['versions'])
    for name, record in install['modules'].items():
        path = resolve_recorded_path(record)
        check('module:' + name, path.exists() and sha(path) == record['sha256'])
    completion = json.loads((run / 'completion.json').read_text(encoding='utf-8'))
    check('no-run-failures', not completion.get('failures'), completion.get('failures'))

    cells = {}
    tasks = []
    for case in freeze['cases']:
        for policy in freeze['policies']:
            directory = run / (case['id'] + '_' + policy)
            label = case['id'] + '/' + policy
            if not (directory / 'result.json').exists():
                check('dir:' + label, False)
                continue
            result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
            native = json.loads((directory / 'native.json').read_text(encoding='utf-8'))
            state = json.loads((directory / 'state.json').read_text(encoding='utf-8'))
            origin = native['origin']
            events = result['events']
            with sqlite3.connect(f'file:{(directory / "effects.sqlite").as_posix()}?mode=ro', uri=True) as db:
                rows = db.execute('select id,operation_id,intent from effects').fetchall()
            writes = state.get('writes', [])
            attempts = state.get('attempts', [])
            stale_new = [a for a in attempts if a.get('attempt', 1) > 1 and a.get('allowed') is not True]
            late_original = [w for w in writes if w.get('attempt', 1) == 1 and w.get('allowed') is not True]
            duplicate = len(rows) > 1
            safe = result['terminal'] == 'complete' and len(rows) == 1 and not stale_new
            check('context:' + label, result['context'] == native['context'] == origin['context'])
            check('seq:' + label, [e['seq'] for e in events] == list(range(len(events))))
            check('event-context:' + label, all(e['context'] == origin['context'] for e in events))
            check('initial:' + label, len(native['initial_observations']) == 1)
            check('budget:' + label, len(events) <= (freeze['budget'] if policy == 'clear' else 3),
                  len(events))
            if case['factors']['idempotency'] == 1:
                check('idempotency:' + label, len(rows) <= 1, len(rows))
            if case['factors']['query_complete'] == 0:
                queries = [e['body'] for e in events if e['action'] == 'query']
                check('query-incomplete:' + label,
                      all(body.get('complete') is False for body in queries), queries)
            if case['patch'] is not None and events:
                if policy == 'reauth_retry':
                    check('patch-reauth:' + label,
                          native['final_route'].get('allowed') is True,
                          native['final_route'])
                else:
                    check('patch:' + label, native['final_route'].get('allowed') is False,
                          native['final_route'])
            if policy == 'reauth_retry' and case['factors']['change'] == 'revoke':
                check('reauth:' + label, len(state.get('reauth', [])) >= 1)
            calls = native['calls']
            retries = sum(1 for e in events if e['action'] == 'retry')
            check('append-count:' + label,
                  sum(1 for c in calls if c['tool'] == 'append') == 1 + retries,
                  (sum(1 for c in calls if c['tool'] == 'append'), 1 + retries))
            if policy == 'clear':
                check('clear-no-duplicate:' + label, not duplicate, len(rows))
                check('clear-no-stale-new:' + label, not stale_new, stale_new)
            tasks.append(dict(case=case['id'], policy=policy, terminal=result['terminal'],
                              reason=result['reason'], actions=len(events), rows=len(rows),
                              duplicate=duplicate, stale_new=len(stale_new),
                              late_original=len(late_original), safe=safe,
                              calls=sum(1 for c in calls if c['tool'] != 'drain'),
                              elapsed_ns=result.get('elapsed_ns')))
            cell = cells.setdefault(case['id'], dict(factors=case['factors'], policies={}))
            cell['policies'][policy] = tasks[-1]

    aggregate = {}
    for policy in freeze['policies']:
        subset = [t for t in tasks if t['policy'] == policy]
        aggregate[policy] = dict(tasks=len(subset),
                                 safe=sum(t['safe'] for t in subset),
                                 complete=sum(t['terminal'] == 'complete' for t in subset),
                                 duplicates=sum(t['duplicate'] for t in subset),
                                 stale_new=sum(t['stale_new'] for t in subset),
                                 late_original=sum(t['late_original'] for t in subset),
                                 actions=sum(t['actions'] for t in subset),
                                 calls=sum(t['calls'] for t in subset))
    check('task-count', len(tasks) == len(freeze['cases']) * len(freeze['policies']),
          (len(tasks), len(freeze['cases']) * len(freeze['policies'])))
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
