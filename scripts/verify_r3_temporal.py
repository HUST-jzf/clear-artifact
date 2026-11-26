"""Independent R3 verifier: Temporal baseline vs frozen R1 CLEAR cells."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R1_SEEDS = {0: ROOT / 'runs/R1/attempt2'} | {
    seed: ROOT / f'runs/R1/seed{seed}' for seed in range(1, 10)}
CLI = ROOT / 'sources/R3_temporal/cli/temporal.exe'
WHEELS = ROOT / 'sources/R3_temporal/wheels_sha256.json'


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
        check('freeze:' + name, (run / 'snapshots' / name).exists() and
              sha(run / 'snapshots' / name) == expected)
    check('temporalio-version', install['versions'].get('temporalio') == '1.34.0',
          install['versions'])
    for name, record in install.get('modules', {}).items():
        path = resolve_recorded_path(record)
        check('module:' + name, path.exists() and sha(path) == record['sha256'])
    check('cli-version', freeze['cli']['version'] == '1.9.1', freeze['cli'])
    check('cli-sha256', CLI.exists() and sha(CLI) == freeze['cli']['sha256'], freeze['cli'])
    check('wheels-manifest', WHEELS.exists() and
          sha(WHEELS) == freeze['wheels_sha256'], freeze['wheels_sha256'])
    completion = json.loads((run / 'completion.json').read_text(encoding='utf-8'))
    check('no-run-failures', not completion.get('failures'), completion.get('failures'))

    cells, tasks = {}, []
    for case in freeze['cases']:
        case_id = case['id']
        idem = 1 if case_id.startswith('I1') else 0
        change = 'revoke' if 'Grevoke' in case_id else 'none'
        fault = case_id[-4:]
        cell = cells.setdefault(case_id, dict(factors=dict(idempotency=idem, change=change,
                                                           fault=fault), seeds={}))
        for seed in freeze['seeds']:
            directory = run / f'S{seed}_{case_id}'
            label = f'{case_id}/S{seed}'
            if not (directory / 'result.json').exists():
                check('missing:' + label, False)
                continue
            result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
            expected_dup = idem == 0 and fault in ['lost', 'late']
            expected_stale = change == 'revoke'
            expected_late = 1 if (fault == 'late' and change == 'revoke') else 0
            check('duplicate:' + label, result['duplicate'] is expected_dup,
                  dict(actual=result['duplicate'], expected=expected_dup))
            check('stale:' + label, (result['stale_new'] > 0) is expected_stale,
                  dict(actual=result['stale_new'], expected=expected_stale))
            if idem == 0:
                check('late-original:' + label, result['late_original'] == expected_late,
                      dict(actual=result['late_original'], expected=expected_late))
            check('complete:' + label, result['terminal'] == 'complete', result)
            check('attempts:' + label, result['attempts'] >= 2, result['attempts'])
            check('rows:' + label, result['rows'] == (2 if expected_dup else 1), result['rows'])
            safe = result['terminal'] == 'complete' and result['rows'] == 1 and result['stale_new'] == 0
            task = dict(case=case_id, seed=seed, terminal=result['terminal'],
                        rows=result['rows'], duplicate=result['duplicate'],
                        stale_new=result['stale_new'], late_original=result['late_original'],
                        attempts=result['attempts'], safe=safe)
            tasks.append(task)
            cell['seeds'][seed] = task
            r1 = json.loads((R1_SEEDS[seed] / 'analysis1/verification.json').read_text(encoding='utf-8'))
            clear = r1['cells'][case_id]['policies']['clear']
            check('clear-no-duplicate:' + label, clear['duplicate'] is False, clear)
            check('clear-no-stale:' + label, clear['stale_new'] == 0, clear)
            cell['seeds'][seed]['clear'] = dict(terminal=clear['terminal'], safe=clear['safe'],
                                                duplicate=clear['duplicate'],
                                                stale_new=clear['stale_new'])
    aggregate = dict(tasks=len(tasks),
                     safe=sum(t['safe'] for t in tasks),
                     complete=sum(t['terminal'] == 'complete' for t in tasks),
                     duplicates=sum(t['duplicate'] for t in tasks),
                     stale=sum(t['stale_new'] > 0 for t in tasks),
                     attempts=sum(t['attempts'] for t in tasks))
    check('task-count', len(tasks) == 120, len(tasks))
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
