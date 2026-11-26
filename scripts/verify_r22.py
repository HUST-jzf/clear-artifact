"""Independent verification of an R22 steady-state run."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    run = (ROOT / args.run).resolve()
    checks = []

    def check(name, passed, detail=None):
        checks.append(dict(name=name, passed=bool(passed), detail=detail))
        if not passed:
            print('FAIL', name, detail)

    completion = json.loads((run / 'completion.json').read_text(encoding='utf-8'))
    freeze = json.loads((run / 'freeze.json').read_text(encoding='utf-8'))
    tasks, failures = completion['tasks'], completion['failures']
    check('no_failures', not failures, failures[:2])
    check('task_count',
          len(tasks) == len(freeze['policies']) * len(freeze['seeds']), len(tasks))
    for name, digest in freeze['files'].items():
        source = ROOT / name
        check('frozen_file:' + name, source.exists() and sha(source) == digest)
    for name, digest in completion['sealed'].items():
        path = run / name
        check('sealed:' + name, path.exists() and sha(path) == digest)

    index = {}
    for task in tasks:
        key = (task['policy'], task['seed'])
        check('unique:' + ':'.join(map(str, key)), key not in index)
        index[key] = task
    check('index_size', len(index) == len(tasks))

    for policy in freeze['policies']:
        group = [index[(policy, seed)] for seed in freeze['seeds']]
        label = 'serial:' + policy
        check('completed:' + label, all(t['completed'] for t in group),
              sum(t['completed'] for t in group))
        check('safe:' + label, all(t['safe'] for t in group),
              sum(t['safe'] for t in group))
        check('duplicates:' + label, all(t['duplicates'] == 0 for t in group),
              sum(t['duplicates'] for t in group))
        check('false_complete:' + label, all(not t['false_complete'] for t in group))
        calls = {t['http_calls'] for t in group}
        check('http_calls:' + label, calls == {freeze['expected_http_calls'][policy]},
              sorted(calls))
        posts = {t['post_calls'] for t in group}
        check('post_calls:' + label, posts == {len(STEPS)}, sorted(posts))

    stats = json.loads((run / 'serial' / 'private' / 'stats.json')
                       .read_text(encoding='utf-8'))
    check('stats_keys', set(stats) == {t['workflow'] for t in tasks},
          (len(stats), len(tasks)))
    mismatched = []
    for task in tasks:
        served = stats.get(task['workflow'], {})
        rows = {step: int(served.get(step, {}).get('rows', 0)) for step in STEPS}
        if rows != task['rows'] or rows != {step: 1 for step in STEPS}:
            mismatched.append(dict(workflow=task['workflow'], served=rows,
                                   recorded=task['rows']))
    check('stats_match', not mismatched, mismatched[:2])
    check('systems_recorded', len(completion['systems']) == 1, completion['systems'])
    check('throughput_positive', all(item['throughput'] > 0 for item in completion['systems']))
    check('latency_recorded', all(item['p95_ms'] > 0 for item in completion['systems']))

    summary = {}
    for policy in freeze['policies']:
        group = [t for t in tasks if t['policy'] == policy]
        latencies = sorted(t['elapsed_ns'] for t in group)
        summary[policy] = dict(
            workflows=len(group), completed=sum(t['completed'] for t in group),
            safe=sum(t['safe'] for t in group),
            duplicates=sum(t['duplicates'] for t in group),
            http_calls=round(sum(t['http_calls'] for t in group) / len(group), 2),
            post_calls=round(sum(t['post_calls'] for t in group) / len(group), 2),
            median_ms=round(latencies[len(latencies) // 2] / 1e6, 2),
            p95_ms=round(latencies[min(len(latencies) - 1,
                                       int(round(0.95 * (len(latencies) - 1))))] / 1e6, 2))

    report = dict(run=args.run, checks=len(checks),
                  passed=sum(1 for item in checks if item['passed']),
                  failed=[item for item in checks if not item['passed']],
                  systems=completion['systems'], summary=summary,
                  status='pass' if all(item['passed'] for item in checks) else 'fail')
    with (run / 'verification.json').open('w', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(dict(checks=report['checks'], passed=report['passed'],
                          status=report['status']), ensure_ascii=False))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
