"""Independent R7 overhead verifier."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pct(values, q):
    values = sorted(values)
    if not values:
        return 0
    return values[min(len(values) - 1, max(0, int(round((len(values) - 1) * q))))]


def mean(values):
    return sum(values) / len(values) if values else 0


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
    check('task-count', len(completion['tasks']) == 1200, len(completion['tasks']))

    tasks = completion['tasks']
    for item in tasks:
        label = f"{item['case']}:{item['policy']}:R{item['repetition']:02d}"
        check('control-ns:' + label, isinstance(item.get('control_ns'), int)
              and item['control_ns'] >= 0)
        check('timings:' + label, isinstance(item.get('timings'), dict))
        if item['policy'] == 'clear':
            check('clear-safe:' + label, not item['duplicate'] and item['stale_new'] == 0,
                  item)
        if item['policy'] == 'pause':
            check('pause-actions:' + label, item['actions'] == 0
                  and item['counts'].get('query', 0) == 0, item['counts'])
        if item['policy'] == 'query_retry':
            check('query-called:' + label, item['counts'].get('query', 0) >= 1,
                  item['counts'])
        if item['policy'] == 'idem_retry':
            check('idem-no-query:' + label, item['counts'].get('query', 0) == 0,
                  item['counts'])

    aggregate = {}
    for policy in freeze['policies']:
        rows = [t for t in tasks if t['policy'] == policy]
        aggregate[policy] = dict(
            tasks=len(rows),
            safe=sum(t['safe'] for t in rows),
            complete=sum(t['terminal'] == 'complete' for t in rows),
            duplicates=sum(t['duplicate'] for t in rows),
            stale=sum(t['stale_new'] > 0 for t in rows),
            control_p50_ns=pct([t['control_ns'] for t in rows], 0.50),
            control_p95_ns=pct([t['control_ns'] for t in rows], 0.95),
            active_p50_ns=pct([t['timings'].get('active_ns', 0) for t in rows], 0.50),
            active_p95_ns=pct([t['timings'].get('active_ns', 0) for t in rows], 0.95),
            wait_p50_ns=pct([t['timings'].get('wait_ns', 0) for t in rows], 0.50),
            wait_p95_ns=pct([t['timings'].get('wait_ns', 0) for t in rows], 0.95),
            actions_mean=mean([t['actions'] for t in rows]),
            queries_mean=mean([t['counts'].get('query', 0) for t in rows]),
            status_mean=mean([t['counts'].get('status', 0) for t in rows]),
            describe_mean=mean([t['counts'].get('describe', 0) for t in rows]),
            retry_mean=mean([t['counts'].get('retry', 0) for t in rows]))
    cells = {}
    for case in freeze['cases']:
        for policy in freeze['policies']:
            rows = [t for t in tasks if t['case'] == case['id'] and t['policy'] == policy]
            cells[f"{case['id']}:{policy}"] = dict(
                tasks=len(rows), safe=sum(t['safe'] for t in rows),
                control_p50_ns=pct([t['control_ns'] for t in rows], 0.50),
                control_p95_ns=pct([t['control_ns'] for t in rows], 0.95),
                active_p50_ns=pct([t['timings'].get('active_ns', 0) for t in rows], 0.50),
                wait_p50_ns=pct([t['timings'].get('wait_ns', 0) for t in rows], 0.50),
                actions_mean=mean([t['actions'] for t in rows]),
                queries_mean=mean([t['counts'].get('query', 0) for t in rows]))
    return dict(checks=checks, aggregate=aggregate, cells=cells,
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
