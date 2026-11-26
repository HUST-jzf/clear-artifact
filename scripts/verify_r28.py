"""Verify R28 from the third-party servers' own stores and the proxy log."""
import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVERS = ['memory', 'sqlite']
FAULTS = ['lost_response', 'lost_before_effect']
POLICIES = ['clear', 'blind_retry', 'query_retry', 'pause']
SEEDS = list(range(1, 21))
EXPECTED = {
    ('memory', 'lost_response', 'clear'): dict(terminal='complete', rows=1,
                                               duplicates=0),
    ('memory', 'lost_response', 'blind_retry'): dict(terminal='complete', rows=1,
                                                      duplicates=0),
    ('memory', 'lost_response', 'query_retry'): dict(terminal='complete', rows=1,
                                                      duplicates=0),
    ('memory', 'lost_response', 'pause'): dict(terminal='pause', rows=1, duplicates=0),
    ('memory', 'lost_before_effect', 'clear'): dict(terminal='pause', rows=0,
                                                     duplicates=0),
    ('memory', 'lost_before_effect', 'blind_retry'): dict(terminal='complete', rows=1,
                                                           duplicates=0),
    ('memory', 'lost_before_effect', 'query_retry'): dict(terminal='complete', rows=1,
                                                           duplicates=0),
    ('memory', 'lost_before_effect', 'pause'): dict(terminal='pause', rows=0,
                                                     duplicates=0),
    ('sqlite', 'lost_response', 'clear'): dict(terminal='complete', rows=1,
                                               duplicates=0),
    ('sqlite', 'lost_response', 'blind_retry'): dict(terminal='complete', rows=2,
                                                      duplicates=1),
    ('sqlite', 'lost_response', 'query_retry'): dict(terminal='complete', rows=1,
                                                      duplicates=0),
    ('sqlite', 'lost_response', 'pause'): dict(terminal='pause', rows=1, duplicates=0),
    ('sqlite', 'lost_before_effect', 'clear'): dict(terminal='pause', rows=0,
                                                     duplicates=0),
    ('sqlite', 'lost_before_effect', 'blind_retry'): dict(terminal='complete', rows=1,
                                                           duplicates=0),
    ('sqlite', 'lost_before_effect', 'query_retry'): dict(terminal='complete', rows=1,
                                                           duplicates=0),
    ('sqlite', 'lost_before_effect', 'pause'): dict(terminal='pause', rows=0,
                                                     duplicates=0),
}
DROP_KIND = {'lost_response': 'response', 'lost_before_effect': 'request'}


def count_rows(directory, server, token):
    if server == 'memory':
        path = directory / 'memory.jsonl'
        if not path.exists():
            return None
        count = 0
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get('type') == 'entity':
                count += sum(1 for item in record.get('observations', []) if item == token)
        return count
    path = directory / 'store.db'
    if not path.exists():
        return None
    connection = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        return connection.execute('select count(*) from effect where token=?',
                                  (token,)).fetchone()[0]
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    run = ROOT / args.run
    completion = json.loads((run / 'completion.json').read_text(encoding='utf-8'))
    checks = []

    def check(name, got, want):
        checks.append(dict(name=name, ok=got == want, got=got, want=want))

    check('failures', completion['failures'], [])
    check('task_count', len(completion['tasks']),
          len(SERVERS) * len(FAULTS) * len(POLICIES) * len(SEEDS))
    tally = {}
    for server in SERVERS:
        for fault in FAULTS:
            for policy in POLICIES:
                want = EXPECTED[(server, fault, policy)]
                cell = tally.setdefault(f'{server}/{fault}/{policy}',
                                        dict(complete=0, duplicates=0, safe=0))
                for seed in SEEDS:
                    name = f'{server}_{fault}_{policy}_s{seed}'
                    directory = run / name
                    result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
                    proxy = json.loads((directory / 'proxy.json').read_text(encoding='utf-8'))
                    rows = count_rows(directory, server, result['token'])
                    duplicates = max(0, (rows or 0) - 1)
                    check(f'{name}:store_exists', rows is not None, True)
                    check(f'{name}:terminal', result['terminal'], want['terminal'])
                    check(f'{name}:rows', rows, want['rows'])
                    check(f'{name}:duplicates', duplicates, want['duplicates'])
                    check(f'{name}:drop_kind', proxy['kind'], DROP_KIND[fault])
                    check(f'{name}:drop_tool', proxy['name'],
                          'add_observations' if server == 'memory' else 'execute')
                    cell['complete'] += int(result['terminal'] == 'complete')
                    cell['duplicates'] += duplicates
                    cell['safe'] += int(result['terminal'] == 'complete' and duplicates == 0)

    passed = sum(1 for item in checks if item['ok'])
    body = dict(checks=len(checks), passed=passed,
                status='pass' if passed == len(checks) else 'fail',
                cells=tally, failed=[item for item in checks if not item['ok']][:20])
    with (run / 'verification.json').open('w', encoding='utf-8') as stream:
        json.dump(body, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({key: body[key] for key in ['checks', 'passed', 'status']}))
    raise SystemExit(0 if body['status'] == 'pass' else 1)


if __name__ == '__main__':
    main()
