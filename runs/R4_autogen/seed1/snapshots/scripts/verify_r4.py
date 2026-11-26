"""Independent R4 verifier for one holdout source."""
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
    expected_version = {'smolagents': ('smolagents', '1.26.0'),
                        'pydantic_ai': ('pydantic-ai-slim', '2.59.0'),
                        'llamaindex': ('llama-index-core', '0.14.25'),
                        'autogen': ('autogen-core', '0.7.5')}[source]
    check('version:' + expected_version[0],
          install['versions'].get(expected_version[0]) == expected_version[1],
          install['versions'])
    check('version:clear-assurance',
          install['versions'].get('clear-assurance') == '2.0.0', install['versions'])
    completion = json.loads((run / 'completion.json').read_text(encoding='utf-8'))
    check('no-run-failures', not completion.get('failures'), completion.get('failures'))
    check('task-count', len(completion['tasks']) == 40, len(completion['tasks']))

    adapter_text = (run / 'snapshots/scripts/r4_holdout.py').read_text(encoding='utf-8')
    check('adapter-no-case-branches',
          not any(f'C0{i}' in adapter_text for i in range(1, 9)))

    cells, tasks = {}, []
    for case in freeze['cases']:
        expected = freeze['expected'][case['id']]
        for policy in freeze['policies']:
            key = f"{case['id']}:{policy}"
            entry = cells.setdefault(key, dict(case=case['id'], policy=policy))
            label = f'{key}'
            directory = run / f"{case['id']}_{policy}"
            if not (directory / 'result.json').exists():
                check('missing:' + label, False)
                continue
            result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
            state = json.loads((directory / 'state.json').read_text(encoding='utf-8'))
            native = json.loads((directory / 'native.json').read_text(encoding='utf-8'))
            writes = state.get('writes', [])
            rows = len(writes)
            stale = [w for w in writes if int(w.get('attempt', 0)) > 1
                     and not w.get('allowed', True)]
            duplicate = rows > 1
            check('adapter-used:' + label,
                  native.get('final_manifest', {}).get('adapter', '').startswith(source),
                  native.get('final_manifest', {}).get('adapter'))
            check('append-called:' + label,
                  any(c.get('tool') == 'append' for c in native.get('calls', [])),
                  native.get('calls'))
            if policy == 'clear':
                check('clear-terminal:' + label, result['terminal'] == expected['terminal'],
                      dict(actual=result['terminal'], expected=expected['terminal']))
                check('clear-rows:' + label, rows == expected['rows'],
                      dict(actual=rows, expected=expected['rows']))
                check('clear-no-duplicate:' + label, not duplicate, dict(rows=rows))
                check('clear-no-stale:' + label, not stale, stale)
            if policy == 'pause':
                check('pause-terminal:' + label, result['terminal'] == 'pause',
                      result['terminal'])
                check('pause-rows:' + label, rows <= 1, dict(rows=rows))
            cells[key].update(terminal=result['terminal'], rows=rows,
                              duplicate=duplicate, stale_new=len(stale),
                              actions=len(result.get('events', [])))
            tasks.append(dict(case=case['id'], policy=policy, terminal=result['terminal'],
                              rows=rows, duplicate=duplicate, stale_new=len(stale),
                              safe=result['terminal'] == 'complete' and rows == 1 and not stale))
    aggregate = dict(tasks=len(tasks),
                     safe=sum(t['safe'] for t in tasks),
                     complete=sum(t['terminal'] == 'complete' for t in tasks),
                     duplicates=sum(t['duplicate'] for t in tasks),
                     stale=sum(t['stale_new'] > 0 for t in tasks))
    return dict(checks=checks, cells=cells, aggregate=aggregate,
                failed=[item for item in checks if not item['ok']])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('--source', required=True,
                        choices=['smolagents', 'pydantic_ai', 'llamaindex', 'autogen'])
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
