"""Independent verification of an R29 storage measurement."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']


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
    check('task_count', len(tasks) == sum(freeze['sizes']), len(tasks))
    for name, digest in freeze['files'].items():
        source = ROOT / name
        check('frozen_file:' + name, source.exists() and sha(source) == digest)
    for name, digest in completion['sealed'].items():
        path = run / name
        check('sealed:' + name, path.exists() and sha(path) == digest)

    for task in tasks:
        check('completed:' + task['workflow'], task['completed'], task['workflow'])
        check('safe:' + task['workflow'], task['safe'], task['workflow'])
        check('duplicates:' + task['workflow'], task['duplicates'] == 0, task['duplicates'])

    storage = {item['config']: item for item in completion['storage']}
    check('storage_configs', set(storage) == {f'n{size}' for size in freeze['sizes']},
          sorted(storage))
    for size in freeze['sizes']:
        item = storage.get(f'n{size}', {})
        check(f'receipts:n{size}', item.get('receipts') == len(STEPS) * size,
              (item.get('receipts'), len(STEPS) * size))
        check(f'rows:n{size}', item.get('effect_rows') == len(STEPS) * size,
              (item.get('effect_rows'), len(STEPS) * size))
        check(f'bytes:n{size}', item.get('total_bytes', 0) > 0, item.get('total_bytes'))
        check(f'receipt_bytes:n{size}', item.get('receipt_bytes_mean', 0) > 0,
              item.get('receipt_bytes_mean'))

    per_workflow = [storage[f'n{size}']['bytes_per_workflow'] for size in freeze['sizes']]
    spread = max(per_workflow) / min(per_workflow)
    check('linear_growth', spread <= 1.15, dict(per_workflow=per_workflow, spread=round(spread, 3)))

    base = min(per_workflow)
    projection = {label: round(base * count / 1e9, 3)
                  for label, count in [('100k', 100_000), ('1m', 1_000_000)]}
    report = dict(run=args.run, checks=len(checks),
                  passed=sum(1 for item in checks if item['passed']),
                  failed=[item for item in checks if not item['passed']],
                  storage=completion['storage'],
                  bytes_per_workflow=base, projection_gb=projection,
                  status='pass' if all(item['passed'] for item in checks) else 'fail')
    with (run / 'verification.json').open('w', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(dict(checks=report['checks'], passed=report['passed'],
                          bytes_per_workflow=base, projection_gb=projection,
                          status=report['status']), ensure_ascii=False))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
