"""Independent verification of an R32 audit.

Re-reads the frozen SQLite logs itself (it does not trust `audit.json`), and
checks both the per-workflow reconstruction against the runner's ground truth and
the pre-registered aggregate table.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
EXPECTED = {
    ('R15/attempt2', 'idem_off'): dict(workflows=400, duplicates=80, stale=320,
                                       inconsistent=0, false_complete_like=0),
    ('R18/attempt1', 'off_stale'): dict(workflows=200, duplicates=120, stale=0,
                                        inconsistent=0, false_complete_like=0),
    ('R19/attempt2', 'off-faithful-forged'): dict(workflows=100, duplicates=0, stale=0,
                                                  inconsistent=60, false_complete_like=20),
    ('R21/attempt9', 'c32-off'): dict(workflows=200, duplicates=80, stale=0,
                                      inconsistent=0, false_complete_like=0),
    ('R31/attempt1', 'tenant'): dict(workflows=101, duplicates=0, stale=0,
                                     inconsistent=60, false_complete_like=20),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_log(path):
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        ops = db.execute('select op, step, terminal, receipt from ops').fetchall()
        effects = db.execute('select op, step, allowed from effects').fetchall()
    finally:
        db.close()
    rows = {step: 0 for step in STEPS}
    stale = 0
    for _, step, allowed in effects:
        rows[step] = rows.get(step, 0) + 1
        stale += int(not allowed)
    duplicates = sum(max(0, count - 1) for count in rows.values())
    unbound = 0
    inconsistent = 0
    for op, _, terminal, receipt in ops:
        if terminal and not receipt:
            inconsistent += 1
        if receipt and json.loads(receipt).get('operation_id') != op:
            unbound += 1
    false_like = (rows['attach'] == 0 and rows['commit'] >= 1 and rows['notify'] >= 1)
    return dict(rows=rows, duplicates=duplicates, stale=stale, unbound=unbound,
                inconsistent=inconsistent, false_like=false_like)


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

    audit = json.loads((run / 'audit.json').read_text(encoding='utf-8'))
    freeze = json.loads((run / 'freeze.json').read_text(encoding='utf-8'))
    for name, digest in freeze['files'].items():
        source = ROOT / name
        check('frozen_file:' + name, source.exists() and sha(source) == digest)

    for result in audit['results']:
        run_name, config = result['run'], result['config']
        key = (run_name, config)
        want = EXPECTED.get(key)
        check('known_pair:' + '/'.join(key), want is not None, want)
        if not want:
            continue
        directory = ROOT / 'runs' / run_name / config / 'private'
        logs = sorted(directory.glob('*.sqlite'))
        truth = {task['workflow']: task
                 for task in json.loads((ROOT / 'runs' / run_name / 'completion.json')
                                        .read_text(encoding='utf-8'))['tasks']
                 if task['config'] == config}
        check('log_count:' + config, len(logs) == want['workflows'], len(logs))

        mismatched, totals = [], dict(duplicates=0, stale=0, unbound=0,
                                      inconsistent=0, false_like=0)
        for path in logs:
            seen = read_log(path)
            task = truth.get(path.stem)
            if task is None:
                mismatched.append(dict(workflow=path.stem, reason='no_task'))
                continue
            if (seen['rows'] != task['rows'] or seen['duplicates'] != task['duplicates']
                    or seen['stale'] != task['stale_rows']):
                mismatched.append(dict(workflow=path.stem, audited=seen['rows'],
                                       truth=task['rows']))
            totals['duplicates'] += seen['duplicates']
            totals['stale'] += seen['stale']
            totals['unbound'] += seen['unbound']
            totals['inconsistent'] += seen['inconsistent']
            totals['false_like'] += int(seen['false_like'])
        check('reconstruction:' + config, not mismatched, mismatched[:2])
        check('duplicates:' + config, totals['duplicates'] == want['duplicates'],
              dict(got=totals['duplicates'], want=want['duplicates']))
        check('stale:' + config, totals['stale'] == want['stale'],
              dict(got=totals['stale'], want=want['stale']))
        check('unbound:' + config, totals['unbound'] == 0, totals['unbound'])
        check('inconsistent:' + config,
              totals['inconsistent'] == want['inconsistent'],
              dict(got=totals['inconsistent'], want=want['inconsistent']))
        check('false_complete_like:' + config,
              totals['false_like'] == want['false_complete_like'],
              dict(got=totals['false_like'], want=want['false_complete_like']))
        check('audit_agrees:' + config, result['total_duplicates'] == totals['duplicates']
              and result['total_inconsistent'] == totals['inconsistent'],
              dict(audit=result['total_duplicates'], verified=totals['duplicates']))

    report = dict(run=args.run, checks=len(checks),
                  passed=sum(1 for item in checks if item['passed']),
                  failed=[item for item in checks if not item['passed']],
                  status='pass' if all(item['passed'] for item in checks) else 'fail')
    with (run / 'verification.json').open('w', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(dict(checks=report['checks'], passed=report['passed'],
                          status=report['status']), ensure_ascii=False))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
