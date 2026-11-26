"""R49 verifier: rebuild every cell from the workflow SQLite files and check the
pre-registered hypotheses (protocol sections 7, 8 and 11).

Recorded metrics are never trusted.  Committed effects, stale effects,
provisional rows, duplicates and rejections are re-read from each workflow's
database, compared with `completion.json`, and only then aggregated.  Cost is
recomputed from the axes reported by the service and from the source files with
`ast`.
"""
import argparse
import ast
import json
import sqlite3
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ['create', 'reserve', 'attach', 'commit', 'notify']
FAULTS = ['lost_return', 'late_commit']
LEVELS = ['L0', 'L1', 'L2', 'L3']
OWNERSHIP = ['self', 'read_only', 'unmodifiable']
LEVEL_PROFILE = {'L0': 'C0', 'L1': 'C3', 'L2': 'C4', 'L3': 'C6'}
EXPECT_PROFILE = {
    'self': {'L0': 'C0', 'L1': 'C3', 'L2': 'C4', 'L3': 'C6'},
    'read_only': {'L0': 'C0', 'L1': 'C3', 'L2': 'C3', 'L3': 'C3'},
    'unmodifiable': {'L0': 'C0', 'L1': 'C0', 'L2': 'C0', 'L3': 'C0'},
}
EXPECT_CLASS = {
    ('self', 'L0'): dict(lost_return='safe_pause', late_commit='safe_pause'),
    ('self', 'L1'): dict(lost_return='safe_complete', late_commit='unsafe'),
    ('self', 'L2'): dict(lost_return='safe_complete', late_commit='safe_complete'),
    ('self', 'L3'): dict(lost_return='safe_complete', late_commit='safe_complete'),
    ('read_only', 'L0'): dict(lost_return='safe_pause', late_commit='safe_pause'),
    ('read_only', 'L1'): dict(lost_return='safe_complete', late_commit='unsafe'),
    ('read_only', 'L2'): dict(lost_return='safe_complete', late_commit='unsafe'),
    ('read_only', 'L3'): dict(lost_return='safe_complete', late_commit='unsafe'),
    ('unmodifiable', 'L0'): dict(lost_return='safe_pause', late_commit='safe_pause'),
    ('unmodifiable', 'L1'): dict(lost_return='safe_pause', late_commit='safe_pause'),
    ('unmodifiable', 'L2'): dict(lost_return='safe_pause', late_commit='safe_pause'),
    ('unmodifiable', 'L3'): dict(lost_return='safe_pause', late_commit='safe_pause'),
}
BASE_ENDPOINTS = 5
CAPABILITY_ENDPOINTS = dict(closure=1, read=1, admission=1, staging=3, dedup=1)
SERVICE_PARTS = {
    'L1': ['lifecycle', 'effects'],
    'L2': ['admit'],
    'L3': ['allocate', 'finalize', 'abort'],
}
CONTROLLER_POLICY = {'C0': 'clear_pause', 'C3': 'clear_evidence',
                     'C4': 'clear_evidence', 'C6': 'clear_fenced'}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def observe(path):
    db = sqlite3.connect(path)
    try:
        committed = {step: dict(rows=count, stale=stale) for step, count, stale in
                     db.execute("select step, count(*), "
                                "sum(case when allowed=0 then 1 else 0 end) "
                                "from effects where status='committed' group by step")}
        provisional = {step: count for step, count in
                       db.execute("select step, count(*) from effects "
                                  "where status='provisional' group by step")}
        rejected = db.execute('select count(*) from rejects').fetchone()[0]
    finally:
        db.close()
    rows = {step: int(committed.get(step, {}).get('rows', 0)) for step in STEPS}
    stale = sum(int(committed.get(step, {}).get('stale', 0)) for step in STEPS)
    return dict(rows=rows, stale=stale,
                provisional=sum(int(provisional.get(step, 0)) for step in STEPS),
                duplicates=sum(max(0, rows[step] - 1) for step in STEPS),
                rejected=int(rejected))


def classify(task, metric):
    if metric['duplicates'] > 0 or metric['stale'] > 0:
        return 'unsafe'
    if task['terminal'] == 'complete':
        if not all(metric['rows'][step] >= 1 for step in STEPS):
            return 'unsafe'
        return 'safe_complete'
    return 'safe_pause'


def endpoints(axes):
    count = BASE_ENDPOINTS
    if axes.get('closure'):
        count += CAPABILITY_ENDPOINTS['closure']
    if axes.get('read') in ('faithful', 'stale'):
        count += CAPABILITY_ENDPOINTS['read']
    if axes.get('admission'):
        count += CAPABILITY_ENDPOINTS['admission']
    if axes.get('staging'):
        count += CAPABILITY_ENDPOINTS['staging']
    if axes.get('dedup'):
        count += CAPABILITY_ENDPOINTS['dedup']
    return count


def source_lines(source, class_name, names):
    tree = ast.parse(source)
    lines = source.splitlines()
    total, found = 0, []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef) or item.name not in names:
                continue
            body = item.body
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body = body[1:]
            start = body[0].lineno if body else item.end_lineno
            for index in range(start, item.end_lineno + 1):
                text = lines[index - 1].strip()
                if text and not text.startswith('#'):
                    total += 1
            found.append(item.name)
    return total, sorted(found)


def function_lines(source, names):
    tree = ast.parse(source)
    lines = source.splitlines()
    total, found = 0, []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name not in names:
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            body = body[1:]
        start = body[0].lineno if body else node.end_lineno
        for index in range(start, node.end_lineno + 1):
            text = lines[index - 1].strip()
            if text and not text.startswith('#'):
                total += 1
        found.append(node.name)
    return total, sorted(found)


def median(values):
    return statistics.median(values) if values else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--out')
    args = parser.parse_args()
    run = Path(args.run)
    freeze = load(run / 'freeze.json')
    completion = load(run / 'completion.json')
    seeds = set(freeze['seeds'])
    tasks = completion['tasks']
    checks, passed, mismatches = [], [], []

    def check(name, actual, expected):
        checks.append(name)
        if actual == expected:
            passed.append(name)
        else:
            print(json.dumps({'check': name, 'actual': actual, 'expected': expected}))

    check('meta.failures', completion['failures'], [])
    check('meta.tasks', len(tasks), len(OWNERSHIP) * len(LEVELS) * len(FAULTS) * len(seeds))
    # The two injected faults are themselves exchange failures on the faulty
    # step (`attach`): a lost return closes the connection, a late commit times
    # out.  Any other exchange failure is infrastructure, not a capability.
    transport = []
    for task in tasks:
        for error in task.get('transport_errors') or []:
            if error.get('step') != 'attach':
                transport.append(dict(workflow=task['workflow'], error=error))
    check('meta.transport-errors', transport, [])

    metrics = {}
    for task in tasks:
        path = run / task['profile'] / 'private' / (task['workflow'] + '.sqlite')
        metric = observe(path)
        metrics[task['workflow']] = metric
        if metric['rows'] != task['rows'] or metric['stale'] != task['stale'] \
                or metric['provisional'] != task['provisional'] \
                or metric['duplicates'] != task['duplicates'] \
                or metric['rejected'] != task['rejected']:
            mismatches.append(dict(workflow=task['workflow'],
                                   recorded=dict(rows=task['rows'], stale=task['stale'],
                                                 provisional=task['provisional'],
                                                 duplicates=task['duplicates'],
                                                 rejected=task['rejected']),
                                   observed=metric))
    check('sqlite.recompute-mismatches', mismatches, [])

    cells = {}
    for task in tasks:
        key = (task['ownership'], task['level'], task['fault'])
        metric = metrics[task['workflow']]
        cells.setdefault(key, []).append(dict(
            seed=task['seed'], profile=task['profile'], terminal=task['terminal'],
            klass=classify(task, metric), requests=task['requests'],
            bytes=task['bytes'], elapsed_ns=task['elapsed_ns'],
            rows=metric['rows'], stale=metric['stale'],
            provisional=metric['provisional'], duplicates=metric['duplicates']))

    for ownership in OWNERSHIP:
        for level in LEVELS:
            for fault in FAULTS:
                key = (ownership, level, fault)
                rows = cells.get(key, [])
                check(f'count.{ownership}.{level}.{fault}', len(rows), len(seeds))
                check(f'class-homogeneous.{ownership}.{level}.{fault}',
                      len({row['klass'] for row in rows}), 1)
                check(f'effective-profile.{ownership}.{level}.{fault}',
                      sorted({row['profile'] for row in rows}),
                      [EXPECT_PROFILE[ownership][level]])
                check(f'class.{ownership}.{level}.{fault}',
                      sorted({row['klass'] for row in rows}),
                      [EXPECT_CLASS[(ownership, level)][fault]])

    def safe_complete(level, fault):
        rows = cells[('self', level, fault)]
        return len(rows) == len(seeds) and all(row['klass'] == 'safe_complete'
                                               for row in rows)

    safe_levels = [level for level in LEVELS
                   if safe_complete(level, 'lost_return') and safe_complete(level, 'late_commit')]
    check('h1.minimum-safe-level-self', safe_levels, ['L2', 'L3'])
    check('h1.l0-pauses-self',
          sorted({row['klass'] for fault in FAULTS for row in cells[('self', 'L0', fault)]}),
          ['safe_pause'])
    check('h1.l1-late-commit-unsafe-self',
          sorted({row['klass'] for row in cells[('self', 'L1', 'late_commit')]}), ['unsafe'])

    read_only_safe = [level for level in LEVELS
                      if all(row['klass'] == 'safe_complete'
                             for fault in FAULTS for row in cells[('read_only', level, fault)])]
    check('h2.read-only-no-safe-level', read_only_safe, [])
    for level in ('L2', 'L3'):
        rows = cells[('read_only', level, 'late_commit')]
        check(f'h2.read-only-{level}-late-commit-duplicates',
              sum(row['duplicates'] for row in rows) > 0, True)

    unmodifiable = [row for level in LEVELS for fault in FAULTS
                    for row in cells[('unmodifiable', level, fault)]]
    check('h3.unmodifiable-pause-rate',
          sum(1 for row in unmodifiable if row['terminal'] == 'pause'), len(unmodifiable))
    check('h3.unmodifiable-no-duplicates',
          sum(row['duplicates'] for row in unmodifiable), 0)
    check('h3.unmodifiable-no-stale', sum(row['stale'] for row in unmodifiable), 0)

    request_median = {}
    byte_median = {}
    for level in LEVELS:
        rows = [row for fault in FAULTS for row in cells[('self', level, fault)]]
        request_median[level] = median([row['requests'] for row in rows])
        byte_median[level] = median([row['bytes'] for row in rows])
    check('h4.requests-l0-lt-l1', request_median['L0'] < request_median['L1'], True)
    check('h4.requests-l0-lt-l2', request_median['L0'] < request_median['L2'], True)
    check('h4.requests-l2-lt-l3', request_median['L2'] < request_median['L3'], True)
    check('h4.requests-l1-near-l2',
          abs(request_median['L1'] - request_median['L2']) <= 1, True)

    service_source = (ROOT / 'scripts' / 'r45_service.py').read_text(encoding='utf-8')
    controller_source = (ROOT / 'scripts' / 'r45_client.py').read_text(encoding='utf-8')
    added, cumulative, found = {}, {}, {}
    for level in LEVELS:
        parts = SERVICE_PARTS.get(level, [])
        count, names = source_lines(service_source, 'Store', parts)
        added[level] = count
        found[level] = names
        cumulative[level] = sum(added[item] for item in LEVELS[:LEVELS.index(level) + 1])
    check('h4.service-parts-found',
          {level: found[level] for level in LEVELS},
          {'L0': [], 'L1': ['effects', 'lifecycle'], 'L2': ['admit'],
           'L3': ['abort', 'allocate', 'finalize']})
    check('h4.service-lines-increasing',
          all(cumulative[LEVELS[i]] < cumulative[LEVELS[i + 1]]
              for i in range(len(LEVELS) - 1)), True)
    check('h4.service-lines-l0', cumulative['L0'], 0)
    controller = {}
    for level, profile in LEVEL_PROFILE.items():
        count, names = function_lines(controller_source, [CONTROLLER_POLICY[profile]])
        controller[level] = count
        check(f'h4.controller-policy.{level}', names, [CONTROLLER_POLICY[profile]])

    endpoint_counts = {profile: endpoints(axes) for profile, axes in freeze['profiles'].items()}
    check('h4.endpoints', endpoint_counts, {'C0': 5, 'C3': 7, 'C4': 8, 'C6': 11})

    cost = {}
    for level in LEVELS:
        profile = LEVEL_PROFILE[level]
        cost[level] = dict(
            requested_level=level, effective_profile=profile,
            controller=CONTROLLER_POLICY[profile],
            endpoints=endpoint_counts[profile],
            endpoints_over_l0=endpoint_counts[profile] - endpoint_counts['C0'],
            service_lines_added=added[level],
            service_lines_cumulative=cumulative[level],
            controller_lines=controller[level], config_items=2,
            requests_median=request_median[level],
            bytes_median=byte_median[level],
            class_lost_return=sorted({row['klass'] for row in cells[('self', level, 'lost_return')]}),
            class_late_commit=sorted({row['klass'] for row in cells[('self', level, 'late_commit')]}),
            pause_rate=sum(1 for fault in FAULTS for row in cells[('self', level, fault)]
                           if row['terminal'] == 'pause') / (2 * len(seeds)))

    table = {}
    for ownership in OWNERSHIP:
        table[ownership] = {}
        for level in LEVELS:
            table[ownership][level] = {
                fault: dict(klass=sorted({row['klass'] for row in cells[(ownership, level, fault)]}),
                            duplicates=sum(row['duplicates'] for row in
                                           cells[(ownership, level, fault)]),
                            stale=sum(row['stale'] for row in cells[(ownership, level, fault)]),
                            pauses=sum(1 for row in cells[(ownership, level, fault)]
                                       if row['terminal'] == 'pause'),
                            requests=median([row['requests'] for row in
                                             cells[(ownership, level, fault)]]))
                for fault in FAULTS}

    summary = dict(checks=len(checks), passed=len(passed),
                   status='pass' if len(passed) == len(checks) else 'fail',
                   mismatches=len(mismatches), table=table, cost=cost,
                   safe_levels_self=safe_levels)
    out = Path(args.out) if args.out else run / 'verification.json'
    out.write_text(json.dumps(dict(summary, failed=[c for c in checks if c not in passed]),
                              ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('status', 'checks', 'passed', 'mismatches')}))
    if summary['status'] != 'pass':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
