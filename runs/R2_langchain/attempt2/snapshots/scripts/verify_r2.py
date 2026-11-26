"""Independent R2 verifier for one source."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(run, source):
    run = Path(run)
    checks = []

    def check(name, ok, detail=None):
        checks.append(dict(name=name, ok=bool(ok), detail=detail))

    freeze = json.loads((run / 'freeze.json').read_text(encoding='utf-8'))
    install = json.loads((run / 'installation.json').read_text(encoding='utf-8'))
    for name, expected in freeze['files'].items():
        check('freeze:' + name, (run / 'snapshots' / name).exists() and
              sha(run / 'snapshots' / name) == expected)
    expected_versions = {'mcp': {'mcp': '1.26.0'},
                         'anyio': {'anyio': '4.12.1'},
                         'langchain': {'langchain-core': '1.0.0', 'anyio': '4.15.1'}}[source]
    for name, expected in expected_versions.items():
        check('version:' + name, install['versions'].get(name) == expected, install['versions'])
    check('version:clear-assurance',
          install['versions'].get('clear-assurance') == '2.0.0', install['versions'])
    completion = json.loads((run / 'completion.json').read_text(encoding='utf-8'))
    check('no-run-failures', not completion.get('failures'), completion.get('failures'))
    check('task-count', len(completion['tasks']) == 500, len(completion['tasks']))

    cells, tasks = {}, []
    transient_seen = 0
    for case in freeze['cases']:
        for policy in freeze['policies']:
            key = f"{case['mode']}:{policy}"
            entry = cells.setdefault(key, dict(mode=case['mode'], policy=policy, seeds={}))
            label = f"{key}/S{case['seed']}"
            directory = run / f"S{case['seed']}_{case['mode']}_{policy}"
            if not (directory / 'result.json').exists():
                check('missing:' + label, False)
                continue
            result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
            state = json.loads((directory / 'state.json').read_text(encoding='utf-8'))
            native = json.loads((directory / 'native.json').read_text(encoding='utf-8'))
            writes = state.get('writes', [])
            rows = len(writes)
            stale = [w for w in writes if int(w.get('attempt', 0)) > 1 and not w.get('allowed', True)]
            late_original = [w for w in writes if int(w.get('attempt', 0)) == 1
                             and case['mode'] == 'late_commit']
            transient = [c for c in native.get('calls', []) if c.get('outcome') == 'transient_error']
            transient_seen += len(transient)
            duplicate = rows > 1
            check('stale:' + label, not stale, stale)
            check('clear-no-duplicate:' + label,
                  policy != 'clear' or not duplicate, dict(rows=rows))
            check('pause-rows:' + label,
                  policy != 'pause' or rows <= 1, dict(rows=rows))
            check('fail-before-rows:' + label,
                  case['mode'] != 'fail_before' or rows <= 1, dict(rows=rows))
            check('late-original:' + label,
                  case['mode'] != 'late_commit' or len(late_original) == 1,
                  dict(rows=rows, late_original=len(late_original)))
            safe = result['terminal'] == 'complete' and rows == 1 and not stale
            task = dict(mode=case['mode'], seed=case['seed'], policy=policy,
                        terminal=result['terminal'], reason=result.get('reason'),
                        rows=rows, duplicate=duplicate, stale_new=len(stale),
                        late_original=len(late_original),
                        pause_with_effect=result['terminal'] == 'pause' and rows > 0,
                        transient=len(transient), safe=safe)
            tasks.append(task)
            entry['seeds'][case['seed']] = task
    check('transient-injected', transient_seen > 0, transient_seen)

    aggregate = dict(tasks=len(tasks),
                     safe=sum(t['safe'] for t in tasks),
                     complete=sum(t['terminal'] == 'complete' for t in tasks),
                     duplicates=sum(t['duplicate'] for t in tasks),
                     pause=sum(t['terminal'] == 'pause' for t in tasks),
                     pause_with_effect=sum(t['pause_with_effect'] for t in tasks))
    return dict(checks=checks, cells=cells, aggregate=aggregate,
                failed=[item for item in checks if not item['ok']])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('--source', required=True, choices=['mcp', 'anyio', 'langchain'])
    parser.add_argument('--output')
    args = parser.parse_args()
    result = verify(args.run, args.source)
    result.update(source=args.source, checks_total=len(result['checks']),
                  checks_passed=sum(1 for item in result['checks'] if item['ok']))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + '\n', encoding='utf-8')
    print(json.dumps(dict(source=args.source, checks_total=result['checks_total'],
                          checks_passed=result['checks_passed'],
                          aggregate=result['aggregate'],
                          failed=result['failed'][:10]), ensure_ascii=False))
    sys.exit(0 if not result['failed'] else 1)


if __name__ == '__main__':
    main()
