"""Independent verification of an R33 WAN-cost run."""
import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
POLICIES = ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']
CALLS = {'clear': 16, 'idem_retry': 11, 'query_retry': 11,
         'reauth_retry': 11, 'pause': 11}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def median_ms(tasks):
    return statistics.median(task['elapsed_ns'] for task in tasks) / 1e6


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
    check('task_count', len(tasks) == len(freeze['rtts']) * len(freeze['policies'])
          * len(freeze['seeds']), len(tasks))
    for name, digest in freeze['files'].items():
        source = ROOT / name
        check('frozen_file:' + name, source.exists() and sha(source) == digest)
    for name, digest in completion['sealed'].items():
        path = run / name
        check('sealed:' + name, path.exists() and sha(path) == digest)

    for rtt in freeze['rtts']:
        for policy in freeze['policies']:
            group = [t for t in tasks if t['rtt'] == rtt and t['policy'] == policy]
            label = f'rtt{rtt}:{policy}'
            check('group_size:' + label, len(group) == len(freeze['seeds']),
                  len(group))
            check('completed:' + label, all(t['completed'] for t in group),
                  sum(t['completed'] for t in group))
            check('safe:' + label, all(t['safe'] for t in group),
                  sum(t['safe'] for t in group))
            check('duplicates:' + label, all(t['duplicates'] == 0 for t in group),
                  sum(t['duplicates'] for t in group))
            calls = {t['http_calls'] for t in group}
            check('http_calls:' + label, calls == {CALLS[policy]}, sorted(calls))
            posts = {t['post_calls'] for t in group}
            check('post_calls:' + label, posts == {len(STEPS)}, sorted(posts))

    deltas = {}
    for rtt in freeze['rtts']:
        clear = [t for t in tasks if t['rtt'] == rtt and t['policy'] == 'clear']
        idem = [t for t in tasks if t['rtt'] == rtt and t['policy'] == 'idem_retry']
        deltas[rtt] = dict(clear_ms=round(median_ms(clear), 2),
                           idem_ms=round(median_ms(idem), 2),
                           delta_ms=round(median_ms(clear) - median_ms(idem), 2),
                           predicted_ms=round(5 * rtt, 2))
        check(f'positive_delta:rtt{rtt}', deltas[rtt]['delta_ms'] > 0, deltas[rtt])
    ordered = [deltas[rtt]['delta_ms'] for rtt in freeze['rtts']]
    check('delta_grows_with_rtt',
          all(later > earlier for earlier, later in zip(ordered, ordered[1:])),
          ordered)
    largest = freeze['rtts'][-1]
    check('delta_at_least_half_prediction',
          deltas[largest]['delta_ms'] >= 0.5 * deltas[largest]['predicted_ms'],
          deltas[largest])

    report = dict(run=args.run, checks=len(checks),
                  passed=sum(1 for item in checks if item['passed']),
                  failed=[item for item in checks if not item['passed']],
                  systems=completion['systems'], deltas=deltas,
                  status='pass' if all(item['passed'] for item in checks) else 'fail')
    with (run / 'verification.json').open('w', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(dict(checks=report['checks'], passed=report['passed'],
                          deltas=deltas, status=report['status']), ensure_ascii=False))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
