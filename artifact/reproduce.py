"""R10 artifact reproduction: recompute the main tables from frozen run artifacts.

The script is stdlib-only and never writes into a frozen run directory.  It:
1. verifies the installed CLEAR 2.0.0 wheel and the frozen artifact hashes;
2. re-runs every shipped verifier and checks its expected check count;
3. independently recomputes R1-R9 aggregates from result/state/SQLite/timing files;
4. writes reproduction.json, tables.md and analysis1/verification.json.

Run from the repository root:
    python artifact/reproduce.py --run-dir runs/R10/attempt1
"""
import argparse
import hashlib
import importlib.metadata
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = json.loads((ROOT / 'artifact/expected.json').read_text(encoding='utf-8'))
WHEEL = ROOT / 'runs/U07/attempt1/dist/clear_assurance-2.0.0-py3-none-any.whl'

R1_RUNS = {
    'mcp': [ROOT / 'runs/R1/attempt2'] + [ROOT / f'runs/R1/seed{s}' for s in range(1, 10)],
    'anyio': [ROOT / 'runs/R1_anyio/attempt1']
             + [ROOT / f'runs/R1_anyio/seed{s}' for s in range(1, 10)],
    'langchain': [ROOT / 'runs/R1_langchain/attempt2']
                 + [ROOT / f'runs/R1_langchain/seed{s}' for s in range(1, 10)],
}
R2_RUNS = {'mcp': ROOT / 'runs/R2_mcp/attempt1',
           'anyio': ROOT / 'runs/R2_anyio/attempt1',
           'langchain': ROOT / 'runs/R2_langchain/attempt2'}
R3_RUNS = {'langgraph': ROOT / 'runs/R3_langgraph/attempt2',
           'temporal': ROOT / 'runs/R3_temporal/attempt3'}
R4_RUNS = {'smolagents': ROOT / 'runs/R4_smolagents/attempt1',
           'pydantic_ai': ROOT / 'runs/R4_pydantic_ai/attempt1'}
R4_SEED_RUNS = {
    'smolagents': [ROOT / 'runs/R4_smolagents/attempt1']
                  + [ROOT / f'runs/R4_smolagents/seed{s}' for s in range(1, 10)],
    'pydantic_ai': [ROOT / 'runs/R4_pydantic_ai/attempt1']
                   + [ROOT / f'runs/R4_pydantic_ai/seed{s}' for s in range(1, 10)],
}
R14_SEED_RUNS = {
    'llamaindex': [ROOT / 'runs/R4_llamaindex/attempt2']
                  + [ROOT / f'runs/R4_llamaindex/seed{s}' for s in range(1, 10)],
    'autogen': [ROOT / 'runs/R4_autogen/attempt2']
               + [ROOT / f'runs/R4_autogen/seed{s}' for s in range(1, 10)],
}
R5_RUN = ROOT / 'runs/R5/attempt1'
R7_RUN = ROOT / 'runs/R7/attempt2'
R8_RUN = ROOT / 'runs/R8/attempt3'
R9_RUN = ROOT / 'runs/R9/attempt1'
R11_RUN = ROOT / 'runs/R11/attempt3'
R13_RUNS = {'anyio': ROOT / 'runs/R13_anyio/attempt1',
            'langchain': ROOT / 'runs/R13_langchain/attempt1'}
R15_RUN = ROOT / 'runs/R15/attempt2'
R16_RUN = ROOT / 'runs/R16/attempt2'
R17_REPORT = ROOT / 'formal/z3_report.json'
R18_RUN = ROOT / 'runs/R18/attempt1'
R19_RUN = ROOT / 'runs/R19/attempt2'
R20_RUN = ROOT / 'runs/R20/attempt1'
R21_RUN = ROOT / 'runs/R21/attempt9'
R22_RUN = ROOT / 'runs/R22/attempt2'
R23_RUN = ROOT / 'runs/R23/attempt1'
R24_RUN = ROOT / 'runs/R24/attempt1'
R29_RUN = ROOT / 'runs/R29/attempt1'
R30_RUN = ROOT / 'runs/R30/attempt1'
R33_RUN = ROOT / 'runs/R33/attempt2'
R25_RUN = ROOT / 'runs/R25/attempt1'
R26_RUN = ROOT / 'runs/R26/attempt1'
R31_RUN = ROOT / 'runs/R31/attempt1'
R32_RUN = ROOT / 'runs/R32/attempt4'
R27_RUN = ROOT / 'runs/R27/attempt2'
R28_RUN = ROOT / 'runs/R28/attempt4'
R34_RUN = ROOT / 'runs/R34/attempt1'
R35_RUN = ROOT / 'runs/R35/attempt1'
R38_RUN = ROOT / 'runs/R38/attempt1'
R36_RUN = ROOT / 'runs/R36/attempt2'
R39_RUN = ROOT / 'runs/R39/attempt4'
R40_RUN = ROOT / 'runs/R40/attempt2'
R41_RUN = ROOT / 'runs/R41/attempt1'
R42_RUN = ROOT / 'runs/R42/attempt1'
R43_RUN = ROOT / 'runs/R43/attempt1'
R44_RUN = ROOT / 'runs/R44/attempt1'
SOURCE_FIELDS = ('adapter', 'version', 'python', 'framework', 'worker_sha256',
                 'host_sha256', 'observer_sha256')

CHECKS = []


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value, exclusive=False):
    mode = 'x' if exclusive else 'w'
    with Path(path).open(mode, encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def check(name, actual, expected, tolerance=None):
    if tolerance is None:
        ok = actual == expected
    else:
        ok = abs(actual - expected) <= tolerance
    CHECKS.append(dict(name=name, ok=bool(ok), actual=actual, expected=expected))
    return ok


def pct(values, q):
    values = sorted(values)
    if not values:
        return 0
    return values[min(len(values) - 1, max(0, int(round((len(values) - 1) * q))))]


def mean(values):
    return sum(values) / len(values) if values else 0


def sqlite_scalar(path, query):
    connection = sqlite3.connect(f'file:{Path(path).as_posix()}?mode=ro', uri=True)
    try:
        return connection.execute(query).fetchone()[0]
    finally:
        connection.close()


def sqlite_rows(path, query):
    connection = sqlite3.connect(f'file:{Path(path).as_posix()}?mode=ro', uri=True)
    try:
        return connection.execute(query).fetchall()
    finally:
        connection.close()


def run_verifier(args):
    process = subprocess.run([sys.executable] + [str(item) for item in args],
                             capture_output=True, text=True)
    if process.returncode != 0:
        return dict(error=process.stderr.strip() or process.stdout.strip(), returncode=process.returncode)
    lines = [line for line in process.stdout.splitlines() if line.strip()]
    return json.loads(lines[-1])


def check_verification(label, args, expected_checks=None):
    body = run_verifier(args)
    if 'error' in body:
        check(label + ':exit-0', False, True)
        return body
    if expected_checks is not None:
        check(label + ':checks-total', body.get('checks_total'), expected_checks)
    check(label + ':checks-passed', body.get('checks_passed'), body.get('checks_total'))
    check(label + ':no-failures', body.get('failed') or [], [])
    return body


def reproduce_r1():
    computed = {}
    tasks = 0
    for source, runs in R1_RUNS.items():
        aggregate = {policy: dict(tasks=0, safe=0, duplicate=0, stale=0)
                     for policy in ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']}
        for run in runs:
            freeze = load(run / 'freeze.json')
            for case in freeze['cases']:
                for policy in freeze['policies']:
                    directory = run / f"{case['id']}_{policy}"
                    result = load(directory / 'result.json')
                    state = load(directory / 'state.json')
                    rows = sqlite_scalar(directory / 'effects.sqlite', 'select count(*) from effects')
                    stale = [item for item in state.get('attempts', [])
                             if item.get('attempt', 1) > 1 and item.get('allowed') is not True]
                    entry = aggregate[policy]
                    entry['tasks'] += 1
                    entry['safe'] += (result['terminal'] == 'complete' and rows == 1 and not stale)
                    entry['duplicate'] += rows > 1
                    entry['stale'] += bool(stale)
                    tasks += 1
        computed[source] = aggregate
        for policy, entry in aggregate.items():
            expected = EXPECTED['r1']['sources'][source][policy]
            check(f'r1:{source}:{policy}:safe', entry['safe'], expected['safe'])
            check(f'r1:{source}:{policy}:duplicate', entry['duplicate'], expected['duplicate'])
            check(f'r1:{source}:{policy}:stale', entry['stale'], expected['stale'])
    check('r1:task-count', tasks, EXPECTED['r1']['tasks'])
    checks = 0
    for run in [item for runs in R1_RUNS.values() for item in runs]:
        body = check_verification('r1-verifier:' + run.name, [ROOT / 'scripts/verify_r1.py', run])
        checks += body.get('checks_total', 0) if isinstance(body, dict) else 0
    check('r1:verification-checks', checks, EXPECTED['r1']['verification_checks'])
    return computed


def reproduce_r2():
    computed = {}
    for source, run in R2_RUNS.items():
        freeze = load(run / 'freeze.json')
        aggregate = dict(tasks=0, safe=0, complete=0, duplicate=0, stale=0,
                         pause=0, pause_with_effect=0, clear_safe=0, clear_duplicate=0)
        for case in freeze['cases']:
            for policy in freeze['policies']:
                directory = run / f"S{case['seed']}_{case['mode']}_{policy}"
                result = load(directory / 'result.json')
                state = load(directory / 'state.json')
                writes = state.get('writes', [])
                rows = len(writes)
                stale = [item for item in writes
                         if item.get('attempt', 1) > 1 and item.get('allowed') is not True]
                aggregate['tasks'] += 1
                aggregate['safe'] += result['terminal'] == 'complete' and rows == 1 and not stale
                aggregate['complete'] += result['terminal'] == 'complete'
                aggregate['duplicate'] += rows > 1
                aggregate['stale'] += bool(stale)
                aggregate['pause'] += result['terminal'] == 'pause'
                aggregate['pause_with_effect'] += result['terminal'] == 'pause' and rows > 0
                if policy == 'clear':
                    aggregate['clear_safe'] += result['terminal'] == 'complete' and rows == 1 and not stale
                    aggregate['clear_duplicate'] += rows > 1
        computed[source] = aggregate
        expected = EXPECTED['r2']['sources'][source]
        for key in ['tasks', 'safe', 'complete', 'duplicate', 'stale', 'pause',
                    'pause_with_effect', 'clear_safe', 'clear_duplicate']:
            check(f'r2:{source}:{key}', aggregate[key], expected[key])
        check_verification('r2-verifier:' + source,
                           [ROOT / 'scripts/verify_r2.py', run, '--source', source],
                           EXPECTED['r2']['verification'][source])
    return computed


def reproduce_r3():
    computed = {}
    for name, run in R3_RUNS.items():
        freeze = load(run / 'freeze.json')
        aggregate = dict(tasks=0, complete=0, safe=0, duplicate=0, stale=0)
        stale_source = 'attempts.sqlite' if name == 'temporal' else 'result.json (attempts not persisted)'
        for case in freeze['cases']:
            for seed in freeze['seeds']:
                directory = run / f'S{seed}_{case["id"]}'
                result = load(directory / 'result.json')
                rows = sqlite_scalar(directory / 'effects.sqlite', 'select count(*) from effects')
                if name == 'temporal':
                    stale = sqlite_scalar(directory / 'effects.sqlite',
                                          'select count(*) from attempts where attempt>1 and allowed=0')
                else:
                    stale = result['stale_new']
                aggregate['tasks'] += 1
                aggregate['complete'] += result['terminal'] == 'complete'
                aggregate['safe'] += result['terminal'] == 'complete' and rows == 1 and stale == 0
                aggregate['duplicate'] += rows > 1
                aggregate['stale'] += stale > 0
        computed[name] = dict(aggregate, stale_source=stale_source)
        expected = EXPECTED['r3'][name]
        for key in ['tasks', 'complete', 'safe', 'duplicate', 'stale']:
            check(f'r3:{name}:{key}', aggregate[key], expected[key])
        script = ROOT / ('scripts/verify_r3_temporal.py' if name == 'temporal' else 'scripts/verify_r3.py')
        check_verification('r3-verifier:' + name, [script, run],
                           EXPECTED['r3']['verification'][name])
    return computed


def reproduce_r4():
    computed = {}
    for source, run in R4_RUNS.items():
        freeze = load(run / 'freeze.json')
        aggregate = dict(tasks=0, safe=0, complete=0, duplicate=0, stale=0,
                         clear_safe=0, clear_pause=0)
        clear_terminal, clear_rows = {}, {}
        for case in freeze['cases']:
            for policy in freeze['policies']:
                directory = run / f"{case['id']}_{policy}"
                result = load(directory / 'result.json')
                state = load(directory / 'state.json')
                writes = state.get('writes', [])
                rows = len(writes)
                stale = [item for item in writes
                         if item.get('attempt', 0) > 1 and item.get('allowed') is not True]
                aggregate['tasks'] += 1
                aggregate['safe'] += result['terminal'] == 'complete' and rows == 1 and not stale
                aggregate['complete'] += result['terminal'] == 'complete'
                aggregate['duplicate'] += rows > 1
                aggregate['stale'] += bool(stale)
                if policy == 'clear':
                    aggregate['clear_safe'] += result['terminal'] == 'complete' and rows == 1 and not stale
                    aggregate['clear_pause'] += result['terminal'] == 'pause'
                    clear_terminal[case['id']] = result['terminal']
                    clear_rows[case['id']] = rows
        computed[source] = dict(aggregate, clear_terminal=clear_terminal, clear_rows=clear_rows)
        expected = EXPECTED['r4']['sources'][source]
        for key in ['tasks', 'safe', 'complete', 'duplicate', 'stale', 'clear_safe', 'clear_pause']:
            check(f'r4:{source}:{key}', aggregate[key], expected[key])
        for case_id, terminal in expected['clear_terminal'].items():
            check(f'r4:{source}:clear-terminal:{case_id}', clear_terminal[case_id], terminal)
        for case_id, rows in expected['clear_rows'].items():
            check(f'r4:{source}:clear-rows:{case_id}', clear_rows[case_id], rows)
        check_verification('r4-verifier:' + source,
                           [ROOT / 'scripts/verify_r4.py', run, '--source', source],
                           EXPECTED['r4']['verification'][source])
    return computed


def reproduce_r5():
    freeze = load(R5_RUN / 'freeze.json')
    aggregate = {policy: dict(tasks=0, safe=0, complete=0, duplicate=0, stale=0, aborted=0)
                 for policy in freeze['policies']}
    for cell in freeze['cells']:
        for policy in freeze['policies']:
            for seed in freeze['seeds']:
                directory = R5_RUN / f"S{seed}_G{cell['change']}I{cell['idempotency']}_{policy}"
                result = load(directory / 'result.json')
                rows = sqlite_scalar(directory / 'effects.sqlite', 'select count(*) from effects')
                stale = sqlite_scalar(directory / 'effects.sqlite',
                                      'select count(*) from effects where allowed=0')
                aborted = sqlite_scalar(directory / 'effects.sqlite',
                                        "select count(*) from controllers where outcome='aborted'")
                entry = aggregate[policy]
                entry['tasks'] += 1
                entry['safe'] += rows == 1 and stale == 0
                entry['complete'] += rows == 1
                entry['duplicate'] += rows > 1
                entry['stale'] += stale > 0
                entry['aborted'] += aborted
    for policy, entry in aggregate.items():
        expected = EXPECTED['r5']['policies'][policy]
        for key in ['tasks', 'safe', 'complete', 'duplicate', 'stale', 'aborted']:
            check(f'r5:{policy}:{key}', entry[key], expected[key])
    check_verification('r5-verifier', [ROOT / 'scripts/verify_r5.py', R5_RUN],
                       EXPECTED['r5']['verification'])
    return aggregate


def reproduce_r7():
    timings = [load(path) for path in R7_RUN.glob('R*/timings.json')]
    check('r7:task-count', len(timings), 1200)
    aggregate = {}
    for policy in ['clear', 'idem_retry', 'query_retry', 'pause']:
        rows = [item for item in timings if item['policy'] == policy]
        entry = dict(
            tasks=len(rows),
            safe=sum(1 for item in rows if item['safe']),
            complete=sum(1 for item in rows if item['terminal'] == 'complete'),
            duplicate=sum(1 for item in rows if item['rows'] > 1),
            stale=sum(1 for item in rows if item['stale_new'] > 0),
            control_p50_ms=round(pct([item['control_ns'] for item in rows], 0.50) / 1e6, 3),
            control_p95_ms=round(pct([item['control_ns'] for item in rows], 0.95) / 1e6, 3),
            active_p50_ms=round(pct([item['timings'].get('active_ns', 0) for item in rows], 0.50) / 1e6, 3),
            wait_p50_ms=round(pct([item['timings'].get('wait_ns', 0) for item in rows], 0.50) / 1e6, 3),
            actions=round(mean([item['actions'] for item in rows]), 2),
            queries=round(mean([item['counts'].get('query', 0) for item in rows]), 2),
            status=round(mean([item['counts'].get('status', 0) for item in rows]), 2),
            describe=round(mean([item['counts'].get('describe', 0) for item in rows]), 2))
        aggregate[policy] = entry
        expected = EXPECTED['r7']['policies'][policy]
        for key in ['tasks', 'safe', 'complete', 'duplicate', 'stale']:
            check(f'r7:{policy}:{key}', entry[key], expected[key])
        for key in ['control_p50_ms', 'control_p95_ms', 'active_p50_ms', 'wait_p50_ms',
                    'actions', 'queries']:
            check(f'r7:{policy}:{key}', entry[key], expected[key], tolerance=0.011)
        if policy == 'clear':
            for key in ['status', 'describe']:
                check(f'r7:{policy}:{key}', entry[key], expected[key], tolerance=0.011)
    case_p50 = {}
    for case in ['normal', 'fail_before', 'lost_return', 'late_commit', 'revoke', 'closure_missing']:
        rows = [item for item in timings if item['case'] == case and item['policy'] == 'clear']
        value = round(pct([item['control_ns'] for item in rows], 0.50) / 1e6, 3)
        case_p50[case] = value
        check(f'r7:clear:{case}:p50', value, EXPECTED['r7']['clear_case_p50_ms'][case],
              tolerance=0.011)
    aggregate['clear_case_p50_ms'] = case_p50
    check_verification('r7-verifier', [ROOT / 'scripts/verify_r7.py', R7_RUN],
                       EXPECTED['r7']['verification'])
    return aggregate


def reproduce_r8():
    freeze = load(R8_RUN / 'freeze.json')
    schemas = {case['id']: case['route'].get('schema') for case in freeze['cases']}
    aggregate = {}
    for case in freeze['cases']:
        for variant in freeze['variants']:
            for seed in freeze['seeds']:
                directory = R8_RUN / f"S{seed}_{case['id']}_{variant}"
                result = load(directory / 'result.json')
                state = load(directory / 'state.json')
                writes = state.get('writes', [])
                rows = len(writes)
                stale_permit = sum(1 for item in writes
                                   if item['believed_allowed'] and not item['allowed'])
                stale_manifest = sum(1 for item in writes
                                     if item['attempt'] > 1 and item['schema'] != schemas[case['id']])
                entry = aggregate.setdefault(variant, dict(
                    tasks=0, safe=0, complete=0, duplicate=0, pause=0,
                    stale_permit=0, stale_manifest=0))
                entry['tasks'] += 1
                entry['safe'] += (result['terminal'] == 'complete' and rows == 1
                                  and not stale_permit and not stale_manifest)
                entry['complete'] += result['terminal'] == 'complete'
                entry['duplicate'] += rows > 1
                entry['pause'] += result['terminal'] != 'complete'
                entry['stale_permit'] += stale_permit > 0
                entry['stale_manifest'] += stale_manifest > 0
    for variant, entry in aggregate.items():
        expected = EXPECTED['r8']['variants'][variant]
        for key in ['tasks', 'safe', 'complete', 'duplicate', 'pause',
                    'stale_permit', 'stale_manifest']:
            check(f'r8:{variant}:{key}', entry[key], expected[key])
    check_verification('r8-verifier', [ROOT / 'scripts/verify_r8.py', R8_RUN],
                       EXPECTED['r8']['verification'])
    return aggregate


def reproduce_r9(run_dir):
    out = run_dir / 'r9_audit'
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(R9_RUN / 'issues.json', out / 'issues.json')
    process = subprocess.run([sys.executable, str(ROOT / 'scripts/audit_r9.py'), '--out', str(out)],
                             capture_output=True, text=True)
    check('r9:audit-exit-0', process.returncode, 0)
    if process.returncode != 0:
        return None
    audit = load(out / 'audit.json')
    expected = EXPECTED['r9']
    check('r9:total-adapter-loc', audit['total_adapter_loc'], expected['total_adapter_loc'])
    check('r9:shared-control-loc', audit['shared_control']['loc'], expected['shared_control_loc'])
    check('r9:config-fields', audit['config_field_count'], expected['config_fields'])
    check('r9:host-shims', len(audit['host_shims']), expected['host_shims'])
    check('r9:issues', audit['issues']['total'], expected['issues'])
    check('r9:unresolved', audit['issues']['unresolved'], expected['unresolved'])
    for row in audit['sources']:
        source = row['source']
        check(f'r9:{source}:loc', row['loc'], expected['sources'][source]['loc'])
        check(f'r9:{source}:methods', row['method_count'], expected['sources'][source]['methods'])
        check(f'r9:{source}:shims', len(row.get('shims', [])), expected['host_shims'])
    check('r9:acceptance', audit['acceptance'], expected['acceptance'])
    check('r9:frozen', all(item['ok'] for item in audit['frozen']), True)
    return audit


def _reproduce_seed_campaign(runs_by_source, expected_all, label):
    computed = {}
    for source, runs in runs_by_source.items():
        expected = expected_all['sources'][source]
        policies = {policy: dict(tasks=0, safe=0, complete=0, duplicate=0, stale=0, pause=0)
                    for policy in ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']}
        conditions = {}
        checks = 0
        for run in runs:
            freeze = load(run / 'freeze.json')
            check(f'{label}:{source}:{run.name}:seed-field', freeze.get('seed', 0),
                  int(run.name.replace('seed', '')) if run.name.startswith('seed') else 0)
            for case in freeze['cases']:
                for policy in freeze['policies']:
                    directory = run / f"{case['id']}_{policy}"
                    result = load(directory / 'result.json')
                    state = load(directory / 'state.json')
                    writes = state.get('writes', [])
                    rows = len(writes)
                    stale = [item for item in writes
                             if item.get('attempt', 0) > 1 and item.get('allowed') is not True]
                    entry = policies[policy]
                    entry['tasks'] += 1
                    entry['safe'] += result['terminal'] == 'complete' and rows == 1 and not stale
                    entry['complete'] += result['terminal'] == 'complete'
                    entry['duplicate'] += rows > 1
                    entry['stale'] += bool(stale)
                    entry['pause'] += result['terminal'] == 'pause'
                    if policy == 'clear':
                        cell = conditions.setdefault(case['id'], dict(
                            count=0, terminals={}, rows={}))
                        cell['count'] += 1
                        cell['terminals'][result['terminal']] = \
                            cell['terminals'].get(result['terminal'], 0) + 1
                        cell['rows'][str(rows)] = cell['rows'].get(str(rows), 0) + 1
            body = check_verification(f'{label}-verifier:' + run.name,
                                      [ROOT / 'scripts/verify_r4.py', run, '--source', source])
            checks += body.get('checks_total', 0) if isinstance(body, dict) else 0
        computed[source] = dict(policies=policies, clear_conditions=conditions,
                                checks=checks)
        for policy, entry in policies.items():
            for key in ['tasks', 'safe', 'complete', 'duplicate', 'stale', 'pause']:
                check(f'{label}:{source}:{policy}:{key}', entry[key],
                      expected['policies'][policy][key])
        for case_id, cell in expected['clear_conditions'].items():
            actual = conditions[case_id]
            check(f'{label}:{source}:clear-count:{case_id}', actual['count'], cell['count'])
            check(f'{label}:{source}:clear-terminal:{case_id}',
                  actual['terminals'], {cell['terminal']: cell['count']})
            check(f'{label}:{source}:clear-rows:{case_id}',
                  actual['rows'], {str(cell['rows']): cell['count']})
        check(f'{label}:{source}:verification-checks', checks,
              expected['verification_per_run'] * expected['runs'])
    total = sum(value['tasks'] for source in computed.values()
                for value in source['policies'].values())
    check(f'{label}:task-count', total, expected_all['total_tasks'])
    return computed


def reproduce_r4_seeds():
    return _reproduce_seed_campaign(R4_SEED_RUNS, EXPECTED['r4_seeds'], 'r4-seeds')


def reproduce_r14_seeds():
    return _reproduce_seed_campaign(R14_SEED_RUNS, EXPECTED['r14'], 'r14-seeds')


def reproduce_r11():
    freeze = load(R11_RUN / 'freeze.json')
    policies = {policy: dict(tasks=0, safe=0, complete=0, duplicate=0, stale=0, pause=0)
                for policy in freeze['policies']}
    clear_cells, crashes = {}, 0
    for case in freeze['cases']:
        for policy in freeze['policies']:
            for seed in freeze['seeds']:
                directory = R11_RUN / f"S{seed}_{case['id']}_{policy}"
                result = load(directory / 'result.json')
                native = load(directory / 'native.json')
                effects = sqlite_rows(directory / 'effects.sqlite',
                                      'select attempt,origin,allowed from effects')
                rows = len(effects)
                stale = sum(1 for attempt, origin, allowed in effects
                            if attempt > 1 and not allowed)
                duplicate = rows > 1
                false_complete = result['terminal'] == 'complete' and rows == 0
                crashes += len(native.get('crashed_markers', [])) == 1
                entry = policies[policy]
                entry['tasks'] += 1
                entry['safe'] += (result['terminal'] == 'complete' and rows <= 1
                                  and not duplicate and stale == 0 and not false_complete)
                entry['complete'] += result['terminal'] == 'complete'
                entry['duplicate'] += duplicate
                entry['stale'] += stale > 0
                entry['pause'] += result['terminal'] == 'pause'
                if policy == 'clear':
                    clear_cells[case['id']] = dict(terminal=result['terminal'], rows=rows)
    for policy, entry in policies.items():
        for key in ['tasks', 'safe', 'complete', 'duplicate', 'stale', 'pause']:
            check(f'r11:{policy}:{key}', entry[key], EXPECTED['r11']['policies'][policy][key])
    for case_id, cell in EXPECTED['r11']['clear_cells'].items():
        check(f'r11:clear:{case_id}:terminal', clear_cells[case_id]['terminal'], cell['terminal'])
        check(f'r11:clear:{case_id}:rows', clear_cells[case_id]['rows'], cell['rows'])
    check('r11:crash-markers', crashes, EXPECTED['r11']['crash_markers'])
    check_verification('r11-verifier', [ROOT / 'scripts/verify_r11.py', R11_RUN],
                       EXPECTED['r11']['verification'])
    return dict(policies=policies, clear_cells=clear_cells, crash_markers=crashes)


def reproduce_r13():
    computed = {}
    for source, run in R13_RUNS.items():
        freeze = load(run / 'freeze.json')
        aggregate = dict(tasks=0, safe=0, complete=0, duplicate=0, stale=0, pause=0,
                         pause_with_effect=0, unqualified_write=0, atomic_rejected=0)
        for case in freeze['cases']:
            for policy in freeze['policies']:
                directory = run / f"S{case['seed']}_{case['mode']}_{policy}"
                result = load(directory / 'result.json')
                native = load(directory / 'native.json')
                effects = sqlite_rows(directory / 'effects.sqlite',
                                      'select attempt,origin,allowed from effects')
                rows = len(effects)
                stale = sum(1 for attempt, origin, allowed in effects
                            if attempt > 1 and not allowed)
                events = result.get('events', [])
                requalified = any(event['action'] == 'qualify'
                                  and event['body'].get('valid') is True for event in events)
                atomic_rejected = any(event['body'].get('state') == 'stale_qualification'
                                      for event in events)
                changed = sorted(key for key in SOURCE_FIELDS
                                 if native['origin']['manifest'].get(key)
                                 != native['final_manifest'].get(key))
                unqualified = (result['terminal'] == 'complete' and rows >= 1
                               and bool(changed) and not requalified)
                aggregate['tasks'] += 1
                aggregate['safe'] += (result['terminal'] == 'complete' and rows == 1
                                      and stale == 0 and not unqualified)
                aggregate['complete'] += result['terminal'] == 'complete'
                aggregate['duplicate'] += rows > 1
                aggregate['stale'] += stale > 0
                aggregate['pause'] += result['terminal'] == 'pause'
                aggregate['pause_with_effect'] += (result['terminal'] == 'pause'
                                                   and rows > 0)
                aggregate['unqualified_write'] += unqualified
                aggregate['atomic_rejected'] += atomic_rejected
        computed[source] = aggregate
        expected = EXPECTED['r13']['sources'][source]
        for key in ['tasks', 'safe', 'complete', 'duplicate', 'stale', 'pause',
                    'pause_with_effect', 'unqualified_write', 'atomic_rejected']:
            check(f'r13:{source}:{key}', aggregate[key], expected[key])
        check_verification('r13-verifier:' + source,
                           [ROOT / 'scripts/verify_r13.py', run, '--source', source],
                           EXPECTED['r13']['verification'][source])
    return computed


def reproduce_r15():
    freeze = load(R15_RUN / 'freeze.json')
    completion = load(R15_RUN / 'completion.json')
    check('r15:task-count', len(completion['tasks']), EXPECTED['r15']['tasks'])
    check('r15:failures', completion['failures'], [])
    computed = {'configs': {}, 'faults': {}}
    for config in freeze['configs']:
        computed['configs'][config] = {}
        for policy in freeze['policies']:
            group = [task for task in completion['tasks']
                     if task['config'] == config and task['policy'] == policy]
            entry = dict(workflows=len(group), safe=sum(t['safe'] for t in group),
                         completed=sum(t['completed'] for t in group),
                         duplicates=sum(t['duplicates'] for t in group),
                         stale_rows=sum(t['stale_rows'] for t in group),
                         pauses=sum(1 for t in group if t['terminal'] == 'paused'),
                         orphan=sum(t['orphan'] for t in group),
                         post_calls=sum(t['post_calls'] for t in group))
            computed['configs'][config][policy] = entry
            for key, value in EXPECTED['r15']['configs'][config][policy].items():
                check(f'r15:{config}:{policy}:{key}', entry[key], value)
        computed['faults'][config] = {}
        for fault in freeze['faults']:
            group = [task for task in completion['tasks']
                     if task['config'] == config and task['fault'] == fault]
            entry = dict(workflows=len(group), safe=sum(t['safe'] for t in group),
                         completed=sum(t['completed'] for t in group),
                         duplicates=sum(t['duplicates'] for t in group),
                         stale_rows=sum(t['stale_rows'] for t in group))
            computed['faults'][config][fault] = entry
            for key, value in EXPECTED['r15']['faults'][config][fault].items():
                check(f'r15:{config}:{fault}:{key}', entry[key], value)
    body = run_verifier([ROOT / 'scripts/verify_r15.py', '--run', R15_RUN])
    check('r15-verifier:exit-0', 'error' not in body, True)
    check('r15-verifier:checks-total', body.get('checks'), EXPECTED['r15']['verification'])
    check('r15-verifier:checks-passed', body.get('passed'), body.get('checks'))
    return computed


def reproduce_r16():
    freeze = load(R16_RUN / 'freeze.json')
    completion = load(R16_RUN / 'completion.json')
    check('r16:task-count', len(completion['tasks']), EXPECTED['r16']['tasks'])
    check('r16:failures', completion['failures'], [])
    computed = {}
    for baseline in freeze['baselines']:
        computed[baseline] = {}
        for config in freeze['configs']:
            group = [task for task in completion['tasks']
                     if task['baseline'] == baseline and task['config'] == config]
            entry = dict(workflows=len(group), safe=sum(t['safe'] for t in group),
                         completed=sum(t['completed'] for t in group),
                         duplicates=sum(t['duplicates'] for t in group),
                         stale_rows=sum(t['stale_rows'] for t in group))
            computed[baseline][config] = entry
            for key, value in EXPECTED['r16']['baselines'][baseline][config].items():
                check(f'r16:{baseline}:{config}:{key}', entry[key], value)
    body = run_verifier([ROOT / 'scripts/verify_r16.py', '--run', R16_RUN])
    check('r16-verifier:exit-0', 'error' not in body, True)
    check('r16-verifier:checks-total', body.get('checks'), EXPECTED['r16']['verification'])
    check('r16-verifier:checks-passed', body.get('passed'), body.get('checks'))
    return computed


def reproduce_r17():
    report = load(R17_REPORT)
    check('r17:tool', report.get('tool'), 'z3')
    check('r17:depth', report.get('depth'), 10)
    for name, value in EXPECTED['r17']['theorems'].items():
        item = report['theorems'][{
            'T1': 'T1_retry_soundness', 'T2': 'T2_admission_atomicity',
            'T3': 'T3_incomplete_evidence_impossibility',
            'T4': 'T4_requalification'}[name]]
        check(f'r17:{name}', item['result'], value)
    for name in ['no_A1_faithful_query', 'no_A2_lifecycle_closure',
                 'no_A3_version_binding', 'no_A4_atomic_admission']:
        item = report['ablations'][name]
        check(f'r17:{name}:result', item['result'], 'sat')
        counterexample = item.get('counterexample') or {}
        check(f'r17:{name}:trace', bool(counterexample.get('trace')),
              True)
        check(f'r17:{name}:depth', 1 <= counterexample.get('depth', 0) <= 10, True)
    check_verification('r17-verifier', [ROOT / 'scripts/verify_r17.py'],
                       EXPECTED['r17']['verification'])
    return dict(theorems={name: report['theorems'][name]['result']
                          for name in report['theorems']},
                ablations={name: report['ablations'][name]['result']
                           for name in report['ablations']})


def reproduce_r18():
    freeze = load(R18_RUN / 'freeze.json')
    completion = load(R18_RUN / 'completion.json')
    check('r18:task-count', len(completion['tasks']), EXPECTED['r18']['tasks'])
    check('r18:failures', completion['failures'], [])
    computed = {}
    for config in freeze['configs']:
        computed[config] = {}
        for policy in freeze['policies']:
            group = [task for task in completion['tasks']
                     if task['config'] == config and task['policy'] == policy]
            entry = dict(workflows=len(group), safe=sum(t['safe'] for t in group),
                         completed=sum(t['completed'] for t in group),
                         duplicates=sum(t['duplicates'] for t in group),
                         pauses=sum(1 for t in group if t['terminal'] == 'paused'))
            computed[config][policy] = entry
            for key, value in EXPECTED['r18']['configs'][config][policy].items():
                check(f'r18:{config}:{policy}:{key}', entry[key], value)
    body = run_verifier([ROOT / 'scripts/verify_r18.py', '--run', R18_RUN])
    check('r18-verifier:exit-0', 'error' not in body, True)
    check('r18-verifier:checks-total', body.get('checks'), EXPECTED['r18']['verification'])
    check('r18-verifier:checks-passed', body.get('passed'), body.get('checks'))
    return computed


def reproduce_grid(name, run, verifier, dimension='config'):
    completion = load(run / 'completion.json')
    check(f'{name}:task-count', len(completion['tasks']), EXPECTED[name]['tasks'])
    check(f'{name}:failures', completion['failures'], [])
    computed = {}
    for task in completion['tasks']:
        entry = computed.setdefault(task[dimension], {}).setdefault(
            task['policy'], dict(workflows=0, safe=0, completed=0, duplicates=0,
                                 false_complete=0, pauses=0))
        entry['workflows'] += 1
        entry['safe'] += int(task['safe'])
        entry['completed'] += int(task['completed'])
        entry['duplicates'] += task['duplicates']
        entry['false_complete'] += int(task['false_complete'])
        entry['pauses'] += int(task['terminal'] == 'paused')
    for config, policies in EXPECTED[name]['configs'].items():
        for policy, want in policies.items():
            got = computed[config][policy]
            for key, value in want.items():
                check(f'{name}:{config}:{policy}:{key}', got[key], value)
    body = run_verifier([ROOT / verifier, '--run', run])
    check(f'{name}-verifier:exit-0', 'error' not in body, True)
    check(f'{name}-verifier:checks-total', body.get('checks'), EXPECTED[name]['verification'])
    check(f'{name}-verifier:checks-passed', body.get('passed'), body.get('checks'))
    return computed


def reproduce_r21():
    computed = reproduce_grid('r21', R21_RUN, 'scripts/verify_r21.py')
    systems = {item['config']: item for item in load(R21_RUN / 'completion.json')['systems']}
    for config, want in EXPECTED['r21']['systems'].items():
        for key, value in want.items():
            check(f'r21:system:{config}:{key}', systems[config][key], value)
    return dict(configs=computed, systems=systems)


def reproduce_r22():
    computed = reproduce_grid('r22', R22_RUN, 'scripts/verify_r22.py')
    tasks = load(R22_RUN / 'completion.json')['tasks']
    for policy, want in EXPECTED['r22']['http_calls'].items():
        calls = {task['http_calls'] for task in tasks if task['policy'] == policy}
        check(f'r22:http-calls:{policy}', sorted(calls), [want])
    return computed


def reproduce_r24():
    return reproduce_grid('r24', R24_RUN, 'scripts/verify_r24.py', dimension='condition')


def reproduce_r29():
    computed = reproduce_grid('r29', R29_RUN, 'scripts/verify_r29.py')
    storage = {item['config']: item for item in load(R29_RUN / 'completion.json')['storage']}
    for config, want in EXPECTED['r29']['storage'].items():
        for key, value in want.items():
            check(f'r29:storage:{config}:{key}', storage[config][key], value)
    return dict(configs=computed, storage=storage)


def reproduce_r30():
    return reproduce_grid('r30', R30_RUN, 'scripts/verify_r30.py')


def reproduce_r33():
    computed = reproduce_grid('r33', R33_RUN, 'scripts/verify_r33.py')
    systems = {item['config']: item for item in load(R33_RUN / 'completion.json')['systems']}
    for config, want in EXPECTED['r33']['systems'].items():
        for key, value in want.items():
            check(f'r33:system:{config}:{key}', systems[config][key], value)
    return dict(configs=computed, systems=systems)


def reproduce_r25():
    computed = reproduce_grid('r25', R25_RUN, 'scripts/verify_r25.py')
    tasks = load(R25_RUN / 'completion.json')['tasks']
    for config, policies in EXPECTED['r25']['double_charge'].items():
        for policy, want in policies.items():
            got = sum(int(task['double_charge']) for task in tasks
                      if task['config'] == config and task['policy'] == policy)
            check(f'r25:double-charge:{config}:{policy}', got, want)
    return computed


def reproduce_r26():
    return reproduce_grid('r26', R26_RUN, 'scripts/verify_r26.py')


def reproduce_r31():
    return reproduce_grid('r31', R31_RUN, 'scripts/verify_r31.py')


def reproduce_r32():
    audit = load(R32_RUN / 'audit.json')
    expected = EXPECTED['r32']
    recorded = {'/'.join([item['run'], item['config']]): item for item in audit['results']}
    check('r32:pair-count', len(recorded), len(expected['pairs']))
    totals = dict(workflows=0, duplicates=0, stale=0, unbound=0,
                  inconsistent=0, false_complete_like=0)
    computed = {}
    for key, want in expected['pairs'].items():
        run_name, config = key.rsplit('/', 1)
        directory = ROOT / 'runs' / run_name / config / 'private'
        logs = sorted(directory.glob('*.sqlite'))
        got = dict(workflows=len(logs), duplicates=0, stale=0, unbound=0,
                   inconsistent=0, false_complete_like=0)
        for path in logs:
            ops = sqlite_rows(path, 'select op, step, terminal, receipt from ops')
            effects = sqlite_rows(path, 'select op, step, allowed from effects')
            rows = {step: 0 for step in ['create', 'reserve', 'attach', 'commit', 'notify']}
            for _, step, allowed in effects:
                rows[step] = rows.get(step, 0) + 1
                got['stale'] += int(not allowed)
            got['duplicates'] += sum(max(0, count - 1) for count in rows.values())
            got['unbound'] += sum(1 for op, _, _, receipt in ops
                                  if receipt and json.loads(receipt).get('operation_id') != op)
            got['inconsistent'] += sum(1 for _, _, terminal, receipt in ops
                                       if terminal and not receipt)
            got['false_complete_like'] += int(rows['attach'] == 0 and rows['commit'] >= 1
                                              and rows['notify'] >= 1)
        computed[key] = got
        for name, value in want.items():
            check(f'r32:{key}:{name}', got[name], value)
        item = recorded.get(key, {})
        check(f'r32:{key}:recorded-workflows', item.get('workflows'), got['workflows'])
        check(f'r32:{key}:recorded-duplicates', item.get('total_duplicates'),
              got['duplicates'])
        check(f'r32:{key}:recorded-stale', item.get('total_stale'), got['stale'])
        check(f'r32:{key}:recorded-inconsistent', item.get('total_inconsistent'),
              got['inconsistent'])
        check(f'r32:{key}:reconstruction', item.get('mismatches'), [])
        check(f'r32:{key}:logs-without-task', item.get('logs_without_task'), [])
        for name in totals:
            totals[name] += got[name]
    check('r32:pair-count-recorded', len(recorded), len(computed))
    for name, value in expected['totals'].items():
        check(f'r32:total:{name}', totals[name], value)
    body = run_verifier([ROOT / 'scripts/verify_r32.py', '--run', R32_RUN])
    check('r32-verifier:exit-0', 'error' not in body, True)
    check('r32-verifier:checks-total', body.get('checks'), expected['verification'])
    check('r32-verifier:checks-passed', body.get('passed'), body.get('checks'))
    return dict(pairs=computed, totals=totals)


def reproduce_r27():
    expected = EXPECTED['r27']
    sources = ['smolagents', 'pydantic_ai', 'llamaindex']
    cases = ['C01_fail_before', 'C02_lost_return', 'C03_late_commit', 'C04_revoke',
             'C05_query_unavailable', 'C06_closure_missing', 'C07_idempotent_lost',
             'C08_normal']
    policy = {'C01_fail_before': ('complete', 1), 'C02_lost_return': ('complete', 1),
              'C03_late_commit': ('complete', 1), 'C04_revoke': ('pause', 0),
              'C05_query_unavailable': ('pause', 1), 'C06_closure_missing': ('complete', 1),
              'C07_idempotent_lost': ('complete', 1), 'C08_normal': ('complete', 1)}
    rows = []
    for source in sources:
        completion = load(R27_RUN / f'completion_{source}.json')
        check(f'r27:{source}:failures', completion['failures'], [])
        check(f'r27:{source}:adapter-changes', completion['adapter_change_lines'], 1)
        check(f'r27:{source}:business-changes', completion['business_changes'], 0)
        check(f'r27:{source}:config-items', len(completion['config_items']), 2)
        check(f'r27:{source}:guard-lines<=60', completion['guard_core_lines'] <= 60, True)
        check(f'r27:{source}:tasks', len(completion['tasks']), 40)
        for seed in range(1, 6):
            for case in cases:
                directory = R27_RUN / f'{source}_s{seed}_{case}'
                result = load(directory / 'result.json')
                state = load(directory / 'state.json')
                want = policy[case]
                check(f'r27:{source}:s{seed}:{case}:terminal', result['terminal'], want[0])
                check(f'r27:{source}:s{seed}:{case}:rows', len(state['writes']), want[1])
                baseline = ROOT / 'runs' / f'R4_{source}' / f'seed{seed}' / f'{case}_clear'
                check(f'r27:{source}:s{seed}:{case}:baseline-terminal', result['terminal'],
                      load(baseline / 'result.json')['terminal'])
                check(f'r27:{source}:s{seed}:{case}:baseline-rows', len(state['writes']),
                      len(load(baseline / 'state.json')['writes']))
                rows.append(dict(source=source, seed=seed, case=case,
                                 terminal=result['terminal'], rows=len(state['writes'])))
    body = run_verifier([ROOT / 'scripts/verify_r27.py', '--run', R27_RUN])
    check('r27-verifier:exit-0', 'error' not in body, True)
    check('r27-verifier:checks-total', body.get('checks'), expected['verification'])
    check('r27-verifier:checks-passed', body.get('passed'), body.get('checks'))
    check('r27:task-count', len(rows), expected['tasks'])
    return dict(rows=rows, guard_core_lines=body.get('guard_core_lines'))


def reproduce_r28():
    expected = EXPECTED['r28']
    completion = load(R28_RUN / 'completion.json')
    check('r28:failures', completion['failures'], [])
    check('r28:task-count', len(completion['tasks']), expected['tasks'])
    rows = []
    for key, want in expected['cells'].items():
        server, fault, policy = key.split('/')
        for seed in range(1, 21):
            directory = R28_RUN / f'{server}_{fault}_{policy}_s{seed}'
            result = load(directory / 'result.json')
            if server == 'memory':
                count = 0
                for line in (directory / 'memory.jsonl').read_text(encoding='utf-8').splitlines():
                    if line.strip():
                        record = json.loads(line)
                        if record.get('type') == 'entity':
                            count += sum(1 for item in record.get('observations', [])
                                         if item == result['token'])
            else:
                connection = sqlite3.connect(f"file:{directory / 'store.db'}?mode=ro", uri=True)
                try:
                    count = connection.execute('select count(*) from effect where token=?',
                                               (result['token'],)).fetchone()[0]
                finally:
                    connection.close()
            proxy = load(directory / 'proxy.json')
            check(f'r28:{key}:s{seed}:terminal', result['terminal'], want['terminal'])
            check(f'r28:{key}:s{seed}:rows', count, want['rows'])
            check(f'r28:{key}:s{seed}:drop', proxy['kind'],
                  'response' if fault == 'lost_response' else 'request')
            rows.append(dict(key=key, seed=seed, terminal=result['terminal'], rows=count))
    body = run_verifier([ROOT / 'scripts/verify_r28.py', '--run', R28_RUN])
    check('r28-verifier:exit-0', 'error' not in body, True)
    check('r28-verifier:checks-total', body.get('checks'), expected['verification'])
    check('r28-verifier:checks-passed', body.get('passed'), body.get('checks'))
    return dict(rows=rows, cells=body.get('cells', {}))


def reproduce_r34():
    expected = EXPECTED['r34']
    steps = ['create', 'reserve', 'attach', 'commit', 'notify']
    completion = load(R34_RUN / 'completion.json')
    check('r34:failures', completion['failures'], [])
    check('r34:task-count', len(completion['tasks']), expected['tasks'])
    rows = []
    for key, want in expected['cells'].items():
        fault, mechanism = key.split('/')
        for seed in range(1, 21):
            directory = R34_RUN / f'{fault}_{mechanism}_s{seed}'
            result = load(directory / 'result.json')
            stats = load(directory / 'private' / 'stats.json')
            observed = stats.get(result['workflow'], {})
            counts = {step: int(observed.get(step, {}).get('rows', 0)) for step in steps}
            duplicates = sum(max(0, counts[step] - 1) for step in steps)
            safe = (all(counts[step] >= 1 for step in steps) and duplicates == 0
                    and all(int(observed.get(step, {}).get('stale', 0)) == 0
                            for step in steps))
            check(f'r34:{key}:s{seed}:rows', counts['attach'], want['rows'])
            check(f'r34:{key}:s{seed}:duplicates', duplicates, want['duplicates'])
            check(f'r34:{key}:s{seed}:safe', safe, want['safe'])
            rows.append(dict(key=key, seed=seed, rows=counts['attach'],
                             duplicates=duplicates, safe=safe))
    body = run_verifier([ROOT / 'scripts/verify_r34.py', '--run', R34_RUN])
    check('r34-verifier:exit-0', 'error' not in body, True)
    check('r34-verifier:checks-total', body.get('checks'), expected['verification'])
    check('r34-verifier:checks-passed', body.get('passed'), body.get('checks'))
    return dict(rows=rows)


def reproduce_r35():
    expected = EXPECTED['r35']
    steps = ['create', 'reserve', 'attach', 'commit', 'notify']
    completion = load(R35_RUN / 'completion.json')
    check('r35:failures', completion['failures'], [])
    check('r35:task-count', len(completion['tasks']), expected['tasks'])
    rows = []
    for key, want in expected['cells'].items():
        condition, policy = key.split('/')
        for seed in range(1, 21):
            directory = R35_RUN / f'{condition}_{policy}_s{seed}'
            result = load(directory / 'result.json')
            stats = load(directory / 'private' / 'stats.json')
            observed = stats.get(result['workflow'], {})
            counts = {step: int(observed.get(step, {}).get('rows', 0)) for step in steps}
            stale = {step: int(observed.get(step, {}).get('stale', 0)) for step in steps}
            completed = all(counts[step] >= 1 for step in steps)
            check(f'r35:{key}:s{seed}:rows', counts['attach'], want['rows'])
            check(f'r35:{key}:s{seed}:stale', stale['attach'], want['stale'])
            check(f'r35:{key}:s{seed}:completed', completed, want['completed'])
            rows.append(dict(key=key, seed=seed, rows=counts['attach'],
                             stale=stale['attach'], completed=completed))
    body = run_verifier([ROOT / 'scripts/verify_r35.py', '--run', R35_RUN])
    check('r35-verifier:exit-0', 'error' not in body, True)
    check('r35-verifier:checks-total', body.get('checks'), expected['verification'])
    check('r35-verifier:checks-passed', body.get('passed'), body.get('checks'))
    return dict(rows=rows)


def reproduce_r38():
    expected = EXPECTED['r38']
    steps = ['create', 'reserve', 'attach', 'commit', 'notify']
    completion = load(R38_RUN / 'completion.json')
    check('r38:failures', completion['failures'], [])
    check('r38:task-count', len(completion['tasks']), expected['tasks'])
    rows = []
    for key, want in expected['cells'].items():
        closure, fault, policy = key.split('/')
        for seed in range(1, 21):
            directory = R38_RUN / f'{closure}_{fault}_{policy}_s{seed}'
            result = load(directory / 'result.json')
            stats = load(directory / 'private' / 'stats.json')
            observed = stats.get(result['workflow'], dict(steps={}, rejected=0))
            counts = {step: int(observed['steps'].get(step, {}).get('rows', 0))
                      for step in steps}
            rejected = int(observed['rejected'])
            completed = all(counts[step] >= 1 for step in steps)
            check(f'r38:{key}:s{seed}:rows', counts['attach'], want['rows'])
            check(f'r38:{key}:s{seed}:completed', completed, want['completed'])
            check(f'r38:{key}:s{seed}:rejected', rejected, want['rejected'])
            rows.append(dict(key=key, seed=seed, rows=counts['attach'],
                             completed=completed, rejected=rejected))
    fence = load(R38_RUN / 'fence_check.json')['configs']
    check('r38:fence-both', fence['both']['duplicate_reachable'],
          expected['fence_check']['both'])
    check('r38:fence-only', fence['fence_only']['duplicate_reachable'],
          expected['fence_check']['fence_only'])
    check('r38:finalize-only', fence['finalize_only']['duplicate_reachable'],
          expected['fence_check']['finalize_only'])
    body = run_verifier([ROOT / 'scripts/verify_r38.py', '--run', R38_RUN])
    check('r38-verifier:exit-0', 'error' not in body, True)
    check('r38-verifier:checks-total', body.get('checks'), expected['verification'])
    check('r38-verifier:checks-passed', body.get('passed'), body.get('checks'))
    return dict(rows=rows)


def reproduce_r36():
    expected = EXPECTED['r36']
    steps = ['create', 'reserve', 'attach', 'commit', 'notify']
    completion = load(R36_RUN / 'completion.json')
    check('r36:failures', completion['failures'], [])
    check('r36:task-count', len(completion['tasks']), expected['tasks'])
    rows = []
    for key, want in expected['cells'].items():
        profile, fault, policy = key.split('/')
        for seed in range(1, 21):
            directory = R36_RUN / f'{profile}_{fault}_{policy}_s{seed}'
            result = load(directory / 'result.json')
            stats = load(directory / 'private' / 'stats.json')
            observed = stats.get(result['workflow'], dict(steps={}, rejected=0))
            counts = {step: int(observed['steps'].get(step, {}).get('rows', 0))
                      for step in steps}
            rejected = int(observed['rejected'])
            completed = all(counts[step] >= 1 for step in steps)
            check(f'r36:{key}:s{seed}:rows', counts['attach'], want['rows'])
            check(f'r36:{key}:s{seed}:completed', completed, want['completed'])
            check(f'r36:{key}:s{seed}:rejected', rejected, want['rejected'])
            rows.append(dict(key=key, seed=seed, rows=counts['attach'],
                             completed=completed, rejected=rejected))
    body = run_verifier([ROOT / 'scripts/verify_r36.py', '--run', R36_RUN])
    check('r36-verifier:exit-0', 'error' not in body, True)
    check('r36-verifier:checks-total', body.get('checks'), expected['verification'])
    check('r36-verifier:checks-passed', body.get('passed'), body.get('checks'))
    return dict(rows=rows)


def reproduce_r39():
    expected = EXPECTED['r39']
    steps = ['create', 'reserve', 'attach', 'commit', 'notify']
    completion = load(R39_RUN / 'completion.json')
    check('r39:failures', completion['failures'], [])
    check('r39:task-count', len(completion['tasks']), expected['tasks'])
    freeze = load(R39_RUN / 'freeze.json')
    check('r39:model', freeze['model'], expected['model'])
    check('r39:drain-seconds', freeze['drain_seconds'], expected['drain_seconds'])
    cells = {}
    for guard in ['blind', 'evidence', 'clear']:
        for fault, runs in expected['runs'].items():
            key = f'{guard}/{fault}'
            want = expected['cells'][key]
            duplicates = rejected = completed = 0
            for index in range(1, runs + 1):
                directory = R39_RUN / f'{guard}_{fault}_r{index}'
                result = load(directory / 'result.json')
                stats = load(directory / 'private' / 'stats.json')
                observed = stats.get(result['workflow'], dict(steps={}, rejected=0))
                counts = {step: int(observed['steps'].get(step, {}).get('rows', 0))
                          for step in steps}
                duplicates += sum(max(0, counts[step] - 1) for step in steps)
                rejected += int(observed['rejected'])
                completed += int(all(counts[step] >= 1 for step in steps))
            check(f'r39:{key}:duplicates', duplicates, want['duplicates'])
            check(f'r39:{key}:rejected', rejected, want['rejected'])
            check(f'r39:{key}:completed', completed, want['completed'])
            cells[key] = dict(duplicates=duplicates, rejected=rejected,
                              completed=completed)
    process = subprocess.run([sys.executable, str(ROOT / 'scripts/verify_r39.py'),
                              '--run', str(R39_RUN)], capture_output=True, text=True)
    lines = [line for line in process.stdout.splitlines() if line.strip()]
    if process.returncode == 0 and lines:
        body = json.loads(lines[0])
    else:
        body = dict(error=process.stderr.strip() or process.stdout.strip())
    check('r39-verifier:exit-0', 'error' not in body, True)
    check('r39-verifier:checks-total', body.get('checks'), expected['verification'])
    check('r39-verifier:checks-passed', body.get('passed'), body.get('checks'))
    return dict(cells=cells)


def reproduce_r40():
    expected = EXPECTED['r40']
    steps = ['create', 'reserve', 'attach', 'commit', 'notify']
    completion = load(R40_RUN / 'completion.json')
    check('r40:failures', completion['failures'], [])
    check('r40:task-count', len(completion['tasks']), expected['tasks'])
    freeze = load(R40_RUN / 'freeze.json')
    check('r40:model', freeze['model'], expected['model'])
    check('r40:drain-seconds', freeze['drain_seconds'], expected['drain_seconds'])
    cells = {}
    for scenario in ['intent_change', 'no_fence_repair']:
        for guard in ['blind', 'evidence', 'clear']:
            key = f'{scenario}/{guard}'
            want = expected['cells'][key]
            agg = dict(duplicates=0, mixed=0, stale=0, residual=0, followed=0,
                       completed=0, paused=0, repaired=0, recovered=0,
                       phase1_completed=0)
            for index in range(1, expected['runs'] + 1):
                directory = R40_RUN / f'{scenario}_{guard}_r{index}'
                result = load(directory / 'result.json')
                stats = load(directory / 'private' / 'stats.json')
                phase1 = load(directory / 'phase1_stats.json')
                observed = stats.get(result['workflow'], dict(steps={}, ops=[]))
                ops = observed.get('ops', [])
                committed = {step: int(observed['steps'].get(step, {}).get('committed', 0))
                             for step in steps}
                first = phase1.get(result['workflow'], dict(steps={}))
                duplicates = sum(max(0, int(entry['rows']) - 1) for entry in ops)
                mixed = sum(1 for entry in ops if len(entry.get('intents') or []) > 1)
                intents = sorted({intent for entry in ops
                                  for intent in entry.get('intents') or []})
                attach = [intent for intent in intents if intent.startswith('ticket:attach:')]
                followed = bool(result['followed'])
                stale = followed and not any(
                    intent.endswith(':' + str(result['last_attach_seat'])) for intent in attach)
                residual = sum(1 for intent in attach
                               if not intent.endswith(':' + str(result['last_attach_seat']))) \
                    if followed else 0
                paused = result.get('paused_list') or []
                recovered = bool(result['repaired'] and paused
                                 and all(committed[step] >= 1 for step in paused))
                phase1_completed = all(
                    int(first['steps'].get(step, {}).get('committed', 0)) >= 1 for step in steps)
                agg['duplicates'] += duplicates
                agg['mixed'] += mixed
                agg['stale'] += int(stale)
                agg['residual'] += residual
                agg['followed'] += int(followed)
                agg['completed'] += int(all(committed[step] >= 1 for step in steps))
                agg['paused'] += int(bool(paused))
                agg['repaired'] += int(result['repaired'])
                agg['recovered'] += int(recovered)
                agg['phase1_completed'] += int(phase1_completed)
            for field in agg:
                check(f'r40:{key}:{field}', agg[field], want[field])
            cells[key] = agg
    process = subprocess.run([sys.executable, str(ROOT / 'scripts/verify_r40.py'),
                              '--run', str(R40_RUN)], capture_output=True, text=True)
    lines = [line for line in process.stdout.splitlines() if line.strip()]
    body = json.loads(lines[0]) if (process.returncode == 0 and lines) else dict(
        error=process.stderr.strip() or process.stdout.strip())
    check('r40-verifier:exit-0', 'error' not in body, True)
    check('r40-verifier:checks-total', body.get('checks'), expected['verification'])
    check('r40-verifier:checks-passed', body.get('passed'), body.get('checks'))
    return dict(cells=cells)


def reproduce_r41():
    expected = EXPECTED['r41']
    report = load(R41_RUN / 'model_check.json')
    check('r41:passed', report['passed'], True)
    check('r41:configs', len(report['configs']), expected['configs'])
    check('r41:t5-depth', report['t5_depth'], expected['t5_depth'])
    check('r41:t6-depth', report['t6_depth'], expected['t6_depth'])
    for name, want in expected['duplicate'].items():
        check(f'r41:{name}:duplicate', report['configs'][name]['duplicate_reachable'], want)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'rerun.json'
        process = subprocess.run([sys.executable, str(ROOT / 'scripts/r41_model_check.py'),
                                  '--out', str(out)], capture_output=True, text=True)
        rerun = json.loads(out.read_text(encoding='utf-8')) if out.exists() else {}
    check('r41:rerun-exit-0', process.returncode, 0)
    check('r41:rerun-passed', rerun.get('passed'), True)
    check('r41:rerun-consistent',
          {name: cell['duplicate_reachable'] for name, cell in rerun.get('configs', {}).items()},
          expected['duplicate'])
    return dict(cells={name: report['configs'][name]['duplicate_reachable']
                       for name in expected['duplicate']})


def reproduce_r42():
    expected = EXPECTED['r42']
    report = load(R42_RUN / 't56_report.json')
    check('r42:schema', report['schema'], 'r42_t56_unbounded_v2')
    check('r42:z3', report['z3_version'], '5.3.1')
    for section in ('t5', 't6'):
        check(f'r42:{section}:depth', report[section]['depth_bound'], None)
        for name, want in expected['safe'][section].items():
            check(f'r42:{section}:{name}:safe', report[section]['configs'][name]['safe'], want)
            check(f'r42:{section}:{name}:init',
                  report[section]['configs'][name]['init_satisfies_inv'], True)
    check('r42:t5:duplicate-trace',
          report['t5']['configs']['t5_no_a6']['duplicate_witness'], expected['t5_trace'])
    check('r42:t5:duplicate-count',
          report['t5']['configs']['t5_no_a6']['duplicate_committed'], 2)
    check('r42:t6:fence-domain',
          'unbounded' in report['t6']['fence_domain'], True)
    check('r42:t5:lease-naive-crash',
          'crash0' in report['t5']['configs']['t5_lease_naive']['duplicate_witness'], True)
    check('r42:t6:reviewer-blocked',
          report['t6']['configs']['t6_both']['reviewer_blocked_at'],
          'not_original')
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'verification.json'
        process = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/verify_r42.py'),
             '--report', str(R42_RUN / 't56_report.json'), '--out', str(out)],
            capture_output=True, text=True)
        body = json.loads(out.read_text(encoding='utf-8')) if out.exists() else {}
    check('r42-verifier:exit-0', process.returncode, 0)
    check('r42-verifier:total', body.get('checks_total'), expected['checks'])
    check('r42-verifier:passed', body.get('checks_passed'), expected['checks'])
    return dict(safe={section: {name: report[section]['configs'][name]['safe']
                                for name in expected['safe'][section]}
                      for section in ('t5', 't6')})


def reproduce_r43():
    expected = EXPECTED['r43']
    result = load(R43_RUN / 'result.json')
    check('r43:schema', result['schema'], 'r43_atomix_original_v1')
    check('r43:commit', result['upstream']['commit'], expected['commit'])
    for key, want in expected['tests'].items():
        check(f'r43:tests:{key}', result['tests'][key], want)
    b3 = result['b3_irreversible']
    check('r43:b3:invalid', b3['invalid_trials'], 3500)
    check('r43:b3:valid', b3['valid_send_trials'], 3500)
    for name, leaks in expected['b3_leaks'].items():
        check(f'r43:b3:{name}:leaks', b3['per_baseline'][name]['leaks'], leaks)
    raw = load(R43_RUN / 'atomix/atomix_b3.json')
    check('r43:b3:rows', len(raw['rows']), 35)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'verification.json'
        process = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/verify_r43.py'),
             '--run', str(R43_RUN), '--out', str(out)],
            capture_output=True, text=True)
        body = json.loads(out.read_text(encoding='utf-8')) if out.exists() else {}
    check('r43-verifier:exit-0', process.returncode, 0)
    check('r43-verifier:total', body.get('checks_total'), expected['checks'])
    check('r43-verifier:passed', body.get('checks_passed'), expected['checks'])
    return dict(leaks={name: b3['per_baseline'][name]['leaks']
                       for name in expected['b3_leaks']})


def reproduce_r44():
    expected = EXPECTED['r44']
    completion = load(R44_RUN / 'completion.json')
    check('r44:failures', completion['failures'], [])
    tasks = completion['tasks']
    check('r44:tasks', len(tasks), expected['tasks'])
    a = [t for t in tasks if t['scenario'] == 'A']
    b = [t for t in tasks if t['scenario'] == 'B']
    check('r44:scenario-a', len(a), expected['scenario_a'])
    check('r44:scenario-b', len(b), expected['scenario_b'])
    for policy in ('fenced', 'dedup_versioned', 'dedup_fresh'):
        rows = [t for t in a if t['policy'] == policy]
        check(f'r44:a:{policy}:count', len(rows), 60)
        check(f'r44:a:{policy}:safe', sum(1 for t in rows if t['safe']),
              expected['safe'][policy])
    for fault, want in expected['duplicates']['dedup_fresh'].items():
        check(f'r44:a:dedup_fresh:{fault}:duplicates',
              sum(t['duplicates'] for t in a
                  if t['policy'] == 'dedup_fresh' and t['fault'] == fault), want)
    for policy, want in expected['false_complete'].items():
        check(f'r44:b:{policy}:false-complete',
              sum(1 for t in b if t['policy'] == policy and t['false_complete']), want)
    fenced = [t for t in a if t['policy'] == 'fenced']
    dedup = [t for t in a if t['policy'] == 'dedup_versioned']
    check('r44:overhead:requests',
          min(t['requests'] for t in fenced) > max(t['requests'] for t in dedup), True)
    check('r44:overhead:bytes',
          min(t['bytes'] for t in fenced) > max(t['bytes'] for t in dedup), True)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'verification.json'
        process = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/verify_r44.py'),
             '--run', str(R44_RUN), '--out', str(out)],
            capture_output=True, text=True)
        body = json.loads(out.read_text(encoding='utf-8')) if out.exists() else {}
    check('r44-verifier:exit-0', process.returncode, 0)
    check('r44-verifier:total', body.get('checks'), expected['checks'])
    check('r44-verifier:passed', body.get('passed'), expected['checks'])
    return dict(a={policy: dict(
        safe=sum(1 for t in a if t['policy'] == policy and t['safe']),
        duplicates=sum(t['duplicates'] for t in a if t['policy'] == policy))
        for policy in ('fenced', 'dedup_versioned', 'dedup_fresh')},
        b={policy: dict(
            false_complete=sum(1 for t in b
                               if t['policy'] == policy and t['false_complete']))
            for policy in ('fenced', 'dedup_versioned', 'dedup_unversioned')})


def build_tables(data):
    lines = ['# R10 reproduced tables', '']
    lines += ['## R1 (7,200 tasks)', '',
              '| source | policy | safe | duplicate | stale |', '|---|---|---:|---:|---:|']
    for source, policies in data['r1'].items():
        for policy in ['clear', 'idem_retry', 'query_retry', 'reauth_retry', 'pause']:
            entry = policies[policy]
            lines.append(f"| {source} | {policy} | {entry['safe']} | {entry['duplicate']} | {entry['stale']} |")
    lines += ['', '## R2 (1,500 tasks)', '',
              '| source | safe | complete | duplicate | stale | pause | pause with effect | CLEAR safe |',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
    for source, entry in data['r2'].items():
        lines.append(f"| {source} | {entry['safe']} | {entry['complete']} | {entry['duplicate']} | "
                     f"{entry['stale']} | {entry['pause']} | {entry['pause_with_effect']} | {entry['clear_safe']} |")
    lines += ['', '## R3 (240 tasks)', '',
              '| baseline | complete | safe | duplicate | stale | stale source |',
              '|---|---:|---:|---:|---:|---|']
    for name, entry in data['r3'].items():
        lines.append(f"| {name} | {entry['complete']} | {entry['safe']} | {entry['duplicate']} | "
                     f"{entry['stale']} | {entry['stale_source']} |")
    lines += ['', '## R4 (80 tasks)', '',
              '| source | safe | complete | duplicate | stale | CLEAR safe |', '|---|---:|---:|---:|---:|---:|']
    for source, entry in data['r4'].items():
        lines.append(f"| {source} | {entry['safe']} | {entry['complete']} | {entry['duplicate']} | "
                     f"{entry['stale']} | {entry['clear_safe']} |")
    lines += ['', '## R5 (400 tasks)', '',
              '| policy | safe | complete(rows=1) | duplicate | stale | aborted |',
              '|---|---:|---:|---:|---:|---:|']
    for policy, entry in data['r5'].items():
        lines.append(f"| {policy} | {entry['safe']} | {entry['complete']} | {entry['duplicate']} | "
                     f"{entry['stale']} | {entry['aborted']} |")
    lines += ['', '## R7 (1,200 tasks, ms)', '',
              '| policy | safe | complete | duplicate | stale | control p50 | control p95 | active p50 | wait p50 | actions |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for policy, entry in data['r7'].items():
        if not isinstance(entry, dict) or 'control_p50_ms' not in entry:
            continue
        lines.append(f"| {policy} | {entry['safe']} | {entry['complete']} | {entry['duplicate']} | "
                     f"{entry['stale']} | {entry['control_p50_ms']} | {entry['control_p95_ms']} | "
                     f"{entry['active_p50_ms']} | {entry['wait_p50_ms']} | {entry['actions']} |")
    lines += ['', '## R8 (450 tasks)', '',
              '| variant | safe | complete | duplicate | pause | stale permit | stale manifest |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for variant, entry in data['r8'].items():
        lines.append(f"| {variant} | {entry['safe']} | {entry['complete']} | {entry['duplicate']} | "
                     f"{entry['pause']} | {entry['stale_permit']} | {entry['stale_manifest']} |")
    lines += ['', '## R9 (static audit)', '',
              '| source | adapter LOC | methods | shims |', '|---|---:|---:|---:|']
    for row in data['r9']['sources']:
        lines.append(f"| {row['source']} | {row['loc']} | {row['method_count']} | {len(row.get('shims', []))} |")
    lines += ['', '## R4 10-seed extension (800 tasks)', '',
              '| source | policy | tasks | safe | complete | duplicate | stale | pause |',
              '|---|---|---:|---:|---:|---:|---:|---:|']
    for source, entry in data['r4_seeds'].items():
        for policy, value in entry['policies'].items():
            lines.append(f"| {source} | {policy} | {value['tasks']} | {value['safe']} | "
                         f"{value['complete']} | {value['duplicate']} | {value['stale']} | "
                         f"{value['pause']} |")
    lines += ['', '## R14 extended hold-out sources (800 tasks)', '',
              '| source | policy | tasks | safe | complete | duplicate | stale | pause |',
              '|---|---|---:|---:|---:|---:|---:|---:|']
    for source, entry in data['r14_seeds'].items():
        for policy, value in entry['policies'].items():
            lines.append(f"| {source} | {policy} | {value['tasks']} | {value['safe']} | "
                         f"{value['complete']} | {value['duplicate']} | {value['stale']} | "
                         f"{value['pause']} |")
    lines += ['', '## R11 real process crash (250 tasks)', '',
              '| policy | tasks | safe | complete | duplicate | stale | pause |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for policy, entry in data['r11']['policies'].items():
        lines.append(f"| {policy} | {entry['tasks']} | {entry['safe']} | {entry['complete']} | "
                     f"{entry['duplicate']} | {entry['stale']} | {entry['pause']} |")
    lines += ['', 'R11 CLEAR cells:', '',
              '| condition | terminal | rows |', '|---|---|---:|']
    for case_id, cell in data['r11']['clear_cells'].items():
        lines.append(f"| {case_id} | {cell['terminal']} | {cell['rows']} |")
    lines += ['', '## R13 change-after-evidence (800 tasks)', '',
              '| source | tasks | safe | complete | duplicate | stale | pause | unqualified | atomic rejected |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for source, entry in data['r13'].items():
        lines.append(f"| {source} | {entry['tasks']} | {entry['safe']} | {entry['complete']} | "
                     f"{entry['duplicate']} | {entry['stale']} | {entry['pause']} | "
                     f"{entry['unqualified_write']} | {entry['atomic_rejected']} |")
    lines += ['', '## R15 end-to-end five-step workflow (800 workflows)', '',
              '| config | policy | workflows | safe | complete | duplicates | stale rows | pauses | orphan | step POSTs |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for config, policies in data['r15']['configs'].items():
        for policy, entry in policies.items():
            lines.append(f"| {config} | {policy} | {entry['workflows']} | {entry['safe']} | "
                         f"{entry['completed']} | {entry['duplicates']} | {entry['stale_rows']} | "
                         f"{entry['pauses']} | {entry['orphan']} | {entry['post_calls']} |")
    lines += ['', '## R16 fair baselines (320 workflows)', '',
              '| baseline | config | workflows | safe | complete | duplicates | stale rows |',
              '|---|---|---:|---:|---:|---:|---:|']
    for baseline, configs in data['r16'].items():
        for config, entry in configs.items():
            lines.append(f"| {baseline} | {config} | {entry['workflows']} | {entry['safe']} | "
                         f"{entry['completed']} | {entry['duplicates']} | {entry['stale_rows']} |")
    lines += ['', '## R17 Z3 inductive model', '',
              '| item | result |', '|---|---|']
    for name, result in data['r17']['theorems'].items():
        lines.append(f"| {name} | {result} |")
    for name, result in data['r17']['ablations'].items():
        lines.append(f"| {name} | {result} |")
    lines += ['', '## R18 evidence-surface degradation (1200 workflows)', '',
              '| config | policy | workflows | safe | complete | duplicates | pauses |',
              '|---|---|---:|---:|---:|---:|---:|']
    for config, policies in data['r18'].items():
        for policy, entry in policies.items():
            lines.append(f"| {config} | {policy} | {entry['workflows']} | {entry['safe']} | "
                         f"{entry['completed']} | {entry['duplicates']} | {entry['pauses']} |")
    for name, title in [('r19', 'R19 evidence redundancy and forged receipts'),
                        ('r20', 'R20 multi-fault and randomised placement')]:
        lines += ['', f'## {title}', '',
                  '| config | policy | workflows | safe | complete | duplicates | false complete | pauses |',
                  '|---|---|---:|---:|---:|---:|---:|---:|']
        for config, policies in data[name].items():
            for policy, entry in policies.items():
                lines.append(f"| {config} | {policy} | {entry['workflows']} | {entry['safe']} | "
                             f"{entry['completed']} | {entry['duplicates']} | "
                             f"{entry['false_complete']} | {entry['pauses']} |")
    lines += ['', '## R21 concurrency (800 workflows)', '',
              '| config | policy | workflows | safe | complete | duplicates | pauses |',
              '|---|---|---:|---:|---:|---:|---:|']
    for config, policies in data['r21']['configs'].items():
        for policy, entry in policies.items():
            lines.append(f"| {config} | {policy} | {entry['workflows']} | {entry['safe']} | "
                         f"{entry['completed']} | {entry['duplicates']} | {entry['pauses']} |")
    lines += ['', '| config | concurrency | wall s | workflows/s | p50 ms | p95 ms |',
              '|---|---:|---:|---:|---:|---:|']
    for config, entry in data['r21']['systems'].items():
        lines.append(f"| {config} | {entry['concurrency']} | {entry['wall_s']} | "
                     f"{entry['throughput']} | {entry['p50_ms']} | {entry['p95_ms']} |")
    lines += ['', '## R22 steady-state cost (200 workflows, no faults)', '',
              '| policy | workflows | safe | complete | duplicates | pauses |',
              '|---|---:|---:|---:|---:|---:|']
    for config, policies in data['r22'].items():
        for policy, entry in policies.items():
            lines.append(f"| {policy} | {entry['workflows']} | {entry['safe']} | "
                         f"{entry['completed']} | {entry['duplicates']} | {entry['pauses']} |")
    lines += ['', '## R23 idempotency key stability (160 workflows)', '',
              '| config | policy | workflows | safe | complete | duplicates | pauses |',
              '|---|---|---:|---:|---:|---:|---:|']
    for config, policies in data['r23'].items():
        for policy, entry in policies.items():
            lines.append(f"| {config} | {policy} | {entry['workflows']} | {entry['safe']} | "
                         f"{entry['completed']} | {entry['duplicates']} | {entry['pauses']} |")
    lines += ['', '## R24 resumable pause (160 workflows, idempotency off)', '',
              '| condition | policy | workflows | safe | complete | duplicates | pauses |',
              '|---|---|---:|---:|---:|---:|---:|']
    for condition, policies in data['r24'].items():
        for policy, entry in policies.items():
            lines.append(f"| {condition} | {policy} | {entry['workflows']} | {entry['safe']} | "
                         f"{entry['completed']} | {entry['duplicates']} | {entry['pauses']} |")
    lines += ['', '## R29 evidence storage cost', '',
              '| config | workflows | bytes/workflow | receipts | effect rows |',
              '|---|---:|---:|---:|---:|']
    for config, entry in data['r29']['storage'].items():
        lines.append(f"| {config} | {entry['workflows']} | {entry['bytes_per_workflow']} | "
                     f"{entry['receipts']} | {entry['effect_rows']} |")
    lines += ['', '## R30 evidence outage (400 workflows)', '',
              '| config | policy | workflows | safe | complete | duplicates | pauses |',
              '|---|---|---:|---:|---:|---:|---:|']
    for config, policies in data['r30'].items():
        for policy, entry in policies.items():
            lines.append(f"| {config} | {policy} | {entry['workflows']} | {entry['safe']} | "
                         f"{entry['completed']} | {entry['duplicates']} | {entry['pauses']} |")
    lines += ['', '## R33 WAN cost (150 workflows)', '',
              '| config | policy | workflows | safe | complete | duplicates |',
              '|---|---|---:|---:|---:|---:|']
    for config, policies in data['r33']['configs'].items():
        for policy, entry in policies.items():
            lines.append(f"| {config} | {policy} | {entry['workflows']} | {entry['safe']} | "
                         f"{entry['completed']} | {entry['duplicates']} |")
    lines += ['', '## R25 payment domain (400 workflows)', '',
              '| config | policy | workflows | safe | complete | duplicates |',
              '|---|---|---:|---:|---:|---:|']
    for config, policies in data['r25'].items():
        for policy, entry in policies.items():
            lines.append(f"| {config} | {policy} | {entry['workflows']} | {entry['safe']} | "
                         f"{entry['completed']} | {entry['duplicates']} |")
    lines += ['', '## R26 instrumentation ladder (240 workflows)', '',
              '| level | policy | workflows | safe | complete | duplicates | pauses |',
              '|---|---|---:|---:|---:|---:|---:|']
    for config, policies in data['r26'].items():
        for policy, entry in policies.items():
            lines.append(f"| {config} | {policy} | {entry['workflows']} | {entry['safe']} | "
                         f"{entry['completed']} | {entry['duplicates']} | {entry['pauses']} |")
    lines += ['', '## R31 cross-tenant receipt binding (101 workflows)', '',
              '| config | policy | workflows | safe | complete | duplicates | false complete | pauses |',
              '|---|---|---:|---:|---:|---:|---:|---:|']
    for config, policies in data['r31'].items():
        for policy, entry in policies.items():
            lines.append(f"| {config} | {policy} | {entry['workflows']} | {entry['safe']} | "
                         f"{entry['completed']} | {entry['duplicates']} | "
                         f"{entry['false_complete']} | {entry['pauses']} |")
    lines += ['', '## R32 offline audit of frozen effect logs (1,001 workflows)', '',
              '| run/config | workflows | duplicate rows | stale rows | unbound receipts | inconsistent ops | false-complete-like |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for key, entry in data['r32']['pairs'].items():
        lines.append(f"| {key} | {entry['workflows']} | {entry['duplicates']} | "
                     f"{entry['stale']} | {entry['unbound']} | {entry['inconsistent']} | "
                     f"{entry['false_complete_like']} |")
    lines += ['', '## R27 decorator path (3 sources x 8 conditions x 5 seeds)', '',
              '| source | seed | condition | terminal | rows |',
              '|---|---:|---|---|---:|']
    for row in data['r27']['rows']:
        lines.append(f"| {row['source']} | {row['seed']} | {row['case']} | "
                     f"{row['terminal']} | {row['rows']} |")
    lines += ['', f"Guard core: {data['r27']['guard_core_lines']} lines.", '',
              '## R28 third-party MCP servers (320 workflows)', '',
              '| server/fault/policy | complete | duplicates | safe |',
              '|---|---:|---:|---:|']
    for key, cell in data['r28']['cells'].items():
        lines.append(f"| {key} | {cell['complete']} | {cell['duplicates']} | "
                     f"{cell['safe']} |")
    lines += ['', '## R34 concurrent dual controllers (120 workflows)', '',
              '| fault/mechanism | attach rows | duplicates | safe |',
              '|---|---:|---:|---:|']
    for row in data['r34']['rows']:
        lines.append(f"| {row['key']} | {row['rows']} | {row['duplicates']} | "
                     f"{row['safe']} |")
    lines += ['', '## R35 same-evidence baseline (120 workflows)', '',
              '| condition/policy | attach rows | stale | completed |',
              '|---|---:|---:|---:|']
    for row in data['r35']['rows']:
        lines.append(f"| {row['key']} | {row['rows']} | {row['stale']} | {row['completed']} |")
    lines += ['', '## R38 fence-ordered settlement (280 workflows)', '',
              '| closure/fault/policy | attach rows | completed | rejected |',
              '|---|---:|---|---:|']
    seen = set()
    for row in data['r38']['rows']:
        if row['key'] in seen:
            continue
        seen.add(row['key'])
        lines.append(f"| {row['key']} | {row['rows']} | {row['completed']} | "
                     f"{row['rejected']} |")
    lines += ['', '## R36 frontier gate vs fence settlement (320 workflows)', '',
              '| profile/fault/policy | attach rows | completed | rejected |',
              '|---|---:|---|---:|']
    seen = set()
    for row in data['r36']['rows']:
        if row['key'] in seen:
            continue
        seen.add(row['key'])
        lines.append(f"| {row['key']} | {row['rows']} | {row['completed']} | "
                     f"{row['rejected']} |")
    lines += ['', '## R39 real LLM agent (84 runs)', '',
              '| guard/fault | duplicates | rejected | completed |',
              '|---|---:|---:|---:|']
    for key in sorted(data['r39']['cells']):
        cell = data['r39']['cells'][key]
        lines.append(f"| {key} | {cell['duplicates']} | {cell['rejected']} | "
                     f"{cell['completed']} |")
    lines += ['', '## R40 intent change and pause/repair (36 runs)', '',
              '| scenario/guard | duplicates | mixed | stale | residual | followed | paused | recovered |',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
    for key in sorted(data['r40']['cells']):
        cell = data['r40']['cells'][key]
        lines.append(f"| {key} | {cell['duplicates']} | {cell['mixed']} | {cell['stale']} | "
                     f"{cell['residual']} | {cell['followed']} | {cell['paused']} | "
                     f"{cell['recovered']} |")
    lines += ['', '## R41 concurrent model check (2 controllers)', '',
              '| config | duplicate reachable |', '|---|---|']
    for key in sorted(data['r41']['cells']):
        lines.append(f"| {key} | {data['r41']['cells'][key]} |")
    lines += ['', '## R42 T5/T6 unbounded inductive check', '',
              '| config | safe |', '|---|---|']
    for section in ('t5', 't6'):
        for key in sorted(data['r42']['safe'][section]):
            lines.append(f"| {key} | {data['r42']['safe'][section][key]} |")
    lines += ['', '## R43 Atomix original system (b3 irreversible)', '',
              '| baseline | leaks (invalid sends) |', '|---|---:|']
    for key in sorted(data['r43']['leaks']):
        lines.append(f"| {key} | {data['r43']['leaks'][key]} |")
    lines += ['', '## R44 equal-capability comparison (198 tasks)', '',
              '| scenario | policy | safe | duplicates | false complete |',
              '|---|---|---:|---:|---:|']
    for policy in ('fenced', 'dedup_versioned', 'dedup_fresh'):
        cell = data['r44']['a'][policy]
        lines.append(f"| A | {policy} | {cell['safe']} | {cell['duplicates']} | - |")
    for policy in ('fenced', 'dedup_versioned', 'dedup_unversioned'):
        cell = data['r44']['b'][policy]
        lines.append(f"| B | {policy} | - | - | {cell['false_complete']} |")
    lines.append('')
    return '\n'.join(lines)


def installation():
    wheel_sha = sha(WHEEL)
    try:
        dist_version = importlib.metadata.version('clear-assurance')
    except importlib.metadata.PackageNotFoundError:
        dist_version = None
    try:
        import clear_assurance
        module = dict(version=clear_assurance.VERSION, file=clear_assurance.__file__,
                      sha256=sha(clear_assurance.__file__))
    except Exception as error:  # pragma: no cover - only for non-artifact environments
        module = dict(error=type(error).__name__ + ': ' + str(error))
    check('installation:dist-version', dist_version, '2.0.0')
    check('installation:module-version', module.get('version'), '2.0.0')
    check('installation:wheel-sha256', wheel_sha,
          load(ROOT / 'runs/U07/attempt1/freeze.json')['wheel']['sha256'])
    return dict(python=sys.version, executable=sys.executable, prefix=sys.prefix,
                dist_version=dist_version, wheel=str(WHEEL), wheel_sha256=wheel_sha,
                wheel_bytes=WHEEL.stat().st_size, module=module)


def freeze_artifact(run_dir):
    names = ['artifact/reproduce.py', 'artifact/expected.json', 'artifact/run.ps1',
             'docs/R10_artifact_reproduction_protocol.md',
             'docs/R4_held_out_sources_10seed_result.md',
             'docs/R11_process_crash_protocol.md', 'docs/R11_process_crash_result.md',
             'docs/R13_post_change_recovery_protocol.md', 'docs/R13_post_change_recovery_result.md',
             'docs/R14_extended_held_out_sources_protocol.md', 'docs/R14_extended_held_out_sources_result.md',
             'docs/R15_end_to_end_workflow_protocol.md', 'docs/R15_end_to_end_workflow_result.md',
             'docs/R16_fair_baselines_protocol.md', 'docs/R16_fair_baselines_result.md',
             'docs/R18_evidence_plane_degradation_protocol.md', 'docs/R18_evidence_plane_degradation_result.md',
             'docs/R19_evidence_redundancy_binding_protocol.md', 'docs/R19_evidence_redundancy_binding_result.md',
             'docs/R20_multi_fault_random_position_protocol.md', 'docs/R20_multi_fault_random_position_result.md',
             'docs/R21_concurrency_throughput_protocol.md', 'docs/R21_concurrency_throughput_result.md',
             'docs/R22_no_fault_cost_protocol.md', 'docs/R22_no_fault_cost_result.md',
             'docs/R23_idempotency_key_stability_protocol.md', 'docs/R23_idempotency_key_stability_result.md',
             'docs/R24_recoverable_pause_protocol.md', 'docs/R24_recoverable_pause_result.md',
             'docs/R29_evidence_storage_cost_protocol.md', 'docs/R29_evidence_storage_cost_result.md',
             'docs/R30_evidence_plane_outage_protocol.md', 'docs/R30_evidence_plane_outage_result.md',
             'docs/R33_wan_cost_protocol.md', 'docs/R33_wan_cost_result.md',
             'docs/R25_payment_domain_protocol.md', 'docs/R25_payment_domain_result.md',
             'docs/R26_minimal_retrofit_ladder_protocol.md', 'docs/R26_minimal_retrofit_ladder_result.md',
             'docs/R31_cross_tenant_binding_protocol.md', 'docs/R31_cross_tenant_binding_result.md',
             'formal/z3_protocol.md', 'formal/z3_model.py', 'formal/z3_report.json',
             'formal/z3_verification.json',
             'scripts/verify_r1.py', 'scripts/verify_r2.py', 'scripts/verify_r3.py',
             'scripts/verify_r3_temporal.py', 'scripts/verify_r4.py', 'scripts/verify_r5.py',
             'scripts/verify_r7.py', 'scripts/verify_r8.py', 'scripts/audit_r9.py',
             'scripts/verify_r11.py', 'scripts/verify_r13.py', 'scripts/summarize_r4_seeds.py',
             'scripts/r15_service.py', 'scripts/r15_client.py', 'scripts/run_r15.py',
             'scripts/verify_r15.py', 'scripts/r16_common.py', 'scripts/r16_temporal.py',
             'scripts/r16_langgraph.py', 'scripts/run_r16.py', 'scripts/verify_r16.py',
             'scripts/r18_service.py', 'scripts/r18_client.py', 'scripts/run_r18.py',
             'scripts/verify_r18.py', 'scripts/verify_r17.py',
             'scripts/r19_service.py', 'scripts/r19_client.py', 'scripts/run_r19.py',
             'scripts/verify_r19.py', 'scripts/r20_client.py', 'scripts/run_r20.py',
             'scripts/verify_r20.py', 'scripts/r21_service.py', 'scripts/r21_client.py',
             'scripts/run_r21.py', 'scripts/verify_r21.py',
             'scripts/run_r22.py', 'scripts/verify_r22.py', 'scripts/r23_client.py',
             'scripts/run_r23.py', 'scripts/verify_r23.py',
             'scripts/r24_service.py', 'scripts/r24_client.py',
             'scripts/run_r24.py', 'scripts/verify_r24.py',
             'scripts/run_r29.py', 'scripts/verify_r29.py',
             'scripts/run_r30.py', 'scripts/verify_r30.py',
             'scripts/r33_proxy.py', 'scripts/run_r33.py', 'scripts/verify_r33.py',
             'scripts/r25_service.py', 'scripts/r25_client.py',
             'scripts/run_r25.py', 'scripts/verify_r25.py',
             'scripts/r26_service.py', 'scripts/run_r26.py', 'scripts/verify_r26.py',
             'scripts/r31_service.py', 'scripts/run_r31.py', 'scripts/verify_r31.py',
             'docs/R32_post_hoc_audit_protocol.md', 'docs/R32_post_hoc_audit_result.md',
             'scripts/run_r32.py', 'scripts/verify_r32.py',
             'docs/R27_middleware_integration_protocol.md', 'docs/R27_middleware_integration_result.md',
             'scripts/r27_guard.py', 'scripts/run_r27.py', 'scripts/verify_r27.py',
             'docs/R28_third_party_services_protocol.md', 'docs/R28_third_party_services_result.md',
             'scripts/r28_proxy.py', 'scripts/r28_client.py', 'scripts/run_r28.py',
             'scripts/verify_r28.py',
             'sources/R28_memory_server/package-lock.json',
             'sources/R28_sqlite_server/package-lock.json',
             'docs/R34_dual_controller_protocol.md',
             'docs/R34_dual_controller_result.md',
             'scripts/r34_service.py', 'scripts/r34_client.py', 'scripts/run_r34.py',
             'scripts/verify_r34.py',
             'docs/R35_same_evidence_baseline_protocol.md',
             'docs/R35_same_evidence_baseline_result.md',
             'scripts/r35_service.py', 'scripts/r35_client.py', 'scripts/run_r35.py',
             'scripts/verify_r35.py',
             'docs/R38_fence_settlement_protocol.md',
             'docs/R38_fence_settlement_result.md',
             'scripts/r38_service.py', 'scripts/r38_client.py', 'scripts/run_r38.py',
             'scripts/verify_r38.py', 'scripts/r38_fence_check.py',
             'docs/R36_frontier_vs_fence_protocol.md',
             'docs/R36_frontier_vs_fence_result.md',
             'scripts/r36_service.py', 'scripts/r36_client.py', 'scripts/run_r36.py',
             'scripts/verify_r36.py',
             'docs/R39_real_llm_protocol.md',
             'docs/R39_real_llm_result.md',
             'scripts/r39_agent.py', 'scripts/run_r39.py', 'scripts/verify_r39.py',
             'docs/R40_intent_change_pause_repair_protocol.md',
             'docs/R40_intent_change_pause_repair_result.md',
             'scripts/r40_agent.py', 'scripts/r40_client.py', 'scripts/r40_service.py',
             'scripts/run_r40.py', 'scripts/verify_r40.py',
             'docs/R41_concurrent_model_check_protocol.md',
             'docs/R41_concurrent_model_check_result.md',
             'scripts/r41_model_check.py',
             'docs/R42_unbounded_induction_protocol.md',
             'docs/R42_unbounded_induction_result.md',
             'formal/t56_model.py', 'scripts/verify_r42.py',
             'docs/R43_atomix_protocol.md',
             'docs/R43_atomix_result.md',
             'scripts/verify_r43.py',
             'docs/R44_equal_capability_protocol.md',
             'docs/R44_equal_capability_result.md',
             'scripts/r44_service.py', 'scripts/r44_client.py', 'scripts/run_r44.py',
             'scripts/verify_r44.py']
    files = {name: sha(ROOT / name) for name in names if (ROOT / name).exists()}
    frozen_runs = ([R5_RUN, R7_RUN, R8_RUN, R9_RUN, R11_RUN, R15_RUN, R16_RUN, R18_RUN,
                    R19_RUN, R20_RUN, R21_RUN, R22_RUN, R23_RUN, R24_RUN, R29_RUN, R30_RUN, R33_RUN, R25_RUN, R26_RUN, R31_RUN, R32_RUN, R27_RUN, R28_RUN, R34_RUN, R35_RUN, R38_RUN, R36_RUN, R39_RUN, R40_RUN, R41_RUN, R42_RUN, R43_RUN, R44_RUN,
                    ROOT / 'runs/R4_seeds/attempt1', ROOT / 'runs/R14_seeds/attempt2']
                   + list(R2_RUNS.values())
                   + list(R3_RUNS.values()) + list(R4_RUNS.values())
                   + list(R13_RUNS.values()))
    frozen_runs += [run for runs in R1_RUNS.values() for run in runs]
    frozen_runs += [run for runs in R4_SEED_RUNS.values() for run in runs]
    frozen_runs += [run for runs in R14_SEED_RUNS.values() for run in runs]
    sealed = {}
    for run in frozen_runs:
        for name in ['freeze.json', 'completion.json', 'installation.json']:
            path = run / name
            if path.exists():
                sealed[path.relative_to(ROOT).as_posix()] = sha(path)
    save(run_dir / 'freeze.json', dict(
        schema='r10_freeze_v1', files=files, wheel=dict(
            path=str(WHEEL), sha256=sha(WHEEL), bytes=WHEEL.stat().st_size),
        sealed=sealed, python=sys.version, executable=sys.executable,
        created_ns=time.time_ns()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', default='runs/R10/attempt1')
    args = parser.parse_args()
    run_dir = (ROOT / args.run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    if (run_dir / 'reproduction.json').exists():
        raise SystemExit('refusing to overwrite ' + str(run_dir / 'reproduction.json'))
    analysis = run_dir / 'analysis1'
    analysis.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter_ns()

    freeze_artifact(run_dir)
    installed = installation()
    save(run_dir / 'installation.json', installed)

    data = dict(r1=reproduce_r1(), r2=reproduce_r2(), r3=reproduce_r3(),
                r4=reproduce_r4(), r5=reproduce_r5(), r7=reproduce_r7(),
                r8=reproduce_r8())
    data['r9'] = reproduce_r9(run_dir)
    data['r4_seeds'] = reproduce_r4_seeds()
    data['r14_seeds'] = reproduce_r14_seeds()
    data['r11'] = reproduce_r11()
    data['r13'] = reproduce_r13()
    data['r15'] = reproduce_r15()
    data['r16'] = reproduce_r16()
    data['r17'] = reproduce_r17()
    data['r18'] = reproduce_r18()
    data['r19'] = reproduce_grid('r19', R19_RUN, 'scripts/verify_r19.py')
    data['r20'] = reproduce_grid('r20', R20_RUN, 'scripts/verify_r20.py')
    data['r21'] = reproduce_r21()
    data['r22'] = reproduce_r22()
    data['r23'] = reproduce_grid('r23', R23_RUN, 'scripts/verify_r23.py')
    data['r24'] = reproduce_r24()
    data['r29'] = reproduce_r29()
    data['r30'] = reproduce_r30()
    data['r33'] = reproduce_r33()
    data['r25'] = reproduce_r25()
    data['r26'] = reproduce_r26()
    data['r31'] = reproduce_r31()
    data['r32'] = reproduce_r32()
    data['r27'] = reproduce_r27()
    data['r28'] = reproduce_r28()
    data['r34'] = reproduce_r34()
    data['r35'] = reproduce_r35()
    data['r38'] = reproduce_r38()
    data['r36'] = reproduce_r36()
    data['r39'] = reproduce_r39()
    data['r40'] = reproduce_r40()
    data['r41'] = reproduce_r41()
    data['r42'] = reproduce_r42()
    data['r43'] = reproduce_r43()
    data['r44'] = reproduce_r44()
    tables = build_tables(data)
    (run_dir / 'tables.md').write_text(tables + '\n', encoding='utf-8')

    total = len(CHECKS)
    passed = sum(1 for item in CHECKS if item['ok'])
    failed = [item for item in CHECKS if not item['ok']]
    body = dict(schema='r10_reproduction_v1', status='pass' if not failed else 'fail',
                checks_total=total, checks_passed=passed,
                experiments={key: True for key in ['r1', 'r2', 'r3', 'r4', 'r4_seeds',
                                                   'r14_seeds', 'r5', 'r7', 'r8', 'r9',
                                                   'r11', 'r13', 'r15', 'r16', 'r17', 'r18',
                                                   'r19', 'r20', 'r21', 'r22', 'r23',
             'r24', 'r29', 'r30', 'r33', 'r25', 'r26', 'r31', 'r32', 'r27', 'r28',
             'r34', 'r35', 'r38', 'r36', 'r39', 'r40', 'r41', 'r42', 'r43', 'r44']},
                checks=CHECKS, failed=failed, tables=tables,
                elapsed_ns=time.perf_counter_ns() - started)
    save(run_dir / 'reproduction.json', body)
    save(analysis / 'verification.json', dict(
        checks=CHECKS, checks_total=total, checks_passed=passed,
        failed=failed, status=body['status']))
    completion = dict(schema='r10_completion_v1', status=body['status'],
                      checks_total=total, checks_passed=passed,
                      experiments=body['experiments'],
                      sealed={path.name: sha(path) for path in
                              [run_dir / 'reproduction.json', run_dir / 'tables.md',
                               run_dir / 'freeze.json', run_dir / 'installation.json',
                               analysis / 'verification.json']},
                      elapsed_ns=body['elapsed_ns'])
    save(run_dir / 'completion.json', completion)
    print(json.dumps(dict(status=body['status'], checks_total=total,
                          checks_passed=passed, failed=len(failed)),
                     ensure_ascii=False))
    raise SystemExit(0 if not failed else 1)


if __name__ == '__main__':
    main()
