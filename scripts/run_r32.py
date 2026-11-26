"""R32: audit frozen effect logs without re-running anything.

Given a run directory produced by the ticket services, read every workflow's
SQLite database and reconstruct, from the log alone:

* rows per step, duplicates (rows beyond the first), stale rows (`allowed=0`);
* receipts that name a different operation (unbound);
* steps the service marked terminal but left without a receipt (inconsistent).

The reconstruction is then compared with the runner's own `completion.json`,
which is the ground truth the controller reported at run time.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
PAIRS = [
    ('R15/attempt2', 'idem_off'),
    ('R18/attempt1', 'off_stale'),
    ('R19/attempt2', 'off-faithful-forged'),
    ('R21/attempt9', 'c32-off'),
    ('R31/attempt1', 'tenant'),
]
NAMES = ['docs/R32_post_hoc_audit_protocol.md', 'scripts/run_r32.py',
         'scripts/verify_r32.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit_workflow(path):
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
    unbound, inconsistent = 0, 0
    for op, _, terminal, receipt in ops:
        if terminal and not receipt:
            inconsistent += 1
        if receipt:
            body = json.loads(receipt)
            if body.get('operation_id') != op:
                unbound += 1
    return dict(rows=rows, duplicates=duplicates, stale_rows=stale,
                unbound_receipts=unbound, inconsistent_ops=inconsistent,
                missing_steps=[step for step in STEPS if rows[step] == 0])


def policy_of(workflow):
    return workflow.rsplit('_', 1)[-1]


def audit(directory):
    findings = {}
    private = directory / 'private'
    for path in sorted(private.glob('*.sqlite')):
        findings[path.stem] = audit_workflow(path)
    return findings


def aggregate(findings):
    out = {}
    for workflow, item in findings.items():
        entry = out.setdefault(policy_of(workflow), dict(
            workflows=0, duplicate_workflows=0, duplicate_rows=0, stale_rows=0,
            unbound_receipts=0, inconsistent_workflows=0, inconsistent_ops=0))
        entry['workflows'] += 1
        entry['duplicate_workflows'] += int(item['duplicates'] > 0)
        entry['duplicate_rows'] += item['duplicates']
        entry['stale_rows'] += item['stale_rows']
        entry['unbound_receipts'] += item['unbound_receipts']
        entry['inconsistent_workflows'] += int(item['inconsistent_ops'] > 0)
        entry['inconsistent_ops'] += item['inconsistent_ops']
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--pairs', default='')
    args = parser.parse_args()
    pairs = PAIRS
    if args.pairs:
        pairs = [(item.split('@')[0], item.split('@')[1])
                 for item in args.pairs.split(',') if item]
    run_dir = ROOT / 'runs' / 'R32' / args.attempt
    run_dir.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in NAMES:
        destination = run_dir / 'snapshots' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
        hashes[name] = sha(ROOT / name)
    started = time.time_ns()
    results = []
    for run_name, config in pairs:
        directory = ROOT / 'runs' / run_name / config
        findings = audit(directory)
        completion = json.loads((ROOT / 'runs' / run_name / 'completion.json')
                                .read_text(encoding='utf-8'))
        truth = {task['workflow']: task for task in completion['tasks']
                 if task['config'] == config}
        mismatched = []
        for workflow, task in truth.items():
            seen = findings.get(workflow)
            if seen is None:
                mismatched.append(dict(workflow=workflow, reason='no_log'))
                continue
            if (seen['rows'] != task['rows']
                    or seen['duplicates'] != task['duplicates']
                    or seen['stale_rows'] != task['stale_rows']):
                mismatched.append(dict(workflow=workflow, audited=seen['rows'],
                                       truth=task['rows']))
        extra = sorted(set(findings) - set(truth))
        results.append(dict(
            run=run_name, config=config, workflows=len(findings),
            truth_workflows=len(truth), policies=aggregate(findings),
            mismatches=mismatched, logs_without_task=extra,
            total_duplicates=sum(item['duplicates'] for item in findings.values()),
            total_stale=sum(item['stale_rows'] for item in findings.values()),
            total_unbound=sum(item['unbound_receipts'] for item in findings.values()),
            total_inconsistent=sum(item['inconsistent_ops'] for item in findings.values())))
    report = dict(pairs=[list(item) for item in pairs], results=results,
                  elapsed_s=round((time.time_ns() - started) / 1e9, 3))
    with (run_dir / 'audit.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    with (run_dir / 'freeze.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(pairs=[list(item) for item in pairs], files=hashes,
                       created_ns=started, python=sys.executable), stream,
                  ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(dict(pairs=len(results),
                          mismatches=sum(len(item['mismatches']) for item in results),
                          elapsed_s=report['elapsed_s']), ensure_ascii=False))


if __name__ == '__main__':
    main()
