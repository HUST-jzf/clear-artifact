"""R11 effect worker: a real subprocess with a JSON-line protocol."""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

STATE = {'invocations': {}, 'writes': [], 'attempts': [], 'reauth': []}
ROOT = None
ROUTE_PATH = None
STATE_PATH = None
DB_PATH = None


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def route():
    return json.loads(ROUTE_PATH.read_text(encoding='utf-8'))


def save_state():
    STATE_PATH.write_text(json.dumps(STATE, ensure_ascii=False, sort_keys=True), encoding='utf-8')


def manifest():
    return dict(adapter='local_subprocess_json', version='r11', python=sys.version.split()[0],
                worker_sha256=sha(__file__), route_sha256=sha(ROUTE_PATH))


def commit(attempt, operation_id, intent):
    conf = route()
    with sqlite3.connect(DB_PATH) as db:
        if conf.get('idempotency') is True:
            row = db.execute('select id,origin,attempt from effects where operation_id=? and intent=? '
                             'order by id limit 1', (operation_id, intent)).fetchone()
            if row is not None:
                return dict(state='committed', record_id=row[0], operation_id=operation_id,
                            intent=intent, generation=1, effect_namespace='effects',
                            attempt=attempt, deduplicated=True)
        allowed = conf.get('allowed') is True
        cur = db.execute('insert into effects(operation_id,intent,origin,attempt,allowed) '
                         'values(?,?,?,?,?)', (operation_id, intent,
                                               'original' if attempt == 1 else 'retry',
                                               attempt, 1 if allowed else 0))
        STATE['writes'].append(dict(attempt=attempt,
                                    origin='original' if attempt == 1 else 'retry',
                                    record_id=cur.lastrowid, allowed=allowed,
                                    at_ns=time.time_ns()))
        save_state()
    return dict(state='committed', record_id=cur.lastrowid, operation_id=operation_id,
                intent=intent, generation=1, effect_namespace='effects', attempt=attempt)


def next_attempt():
    """Attempt numbers live in SQLite so they survive a real process restart."""
    with sqlite3.connect(DB_PATH) as db:
        db.execute('create table if not exists meta(key text primary key, value integer)')
        db.execute("insert or ignore into meta(key,value) values('attempt',0)")
        db.execute("update meta set value=value+1 where key='attempt'")
        return db.execute("select value from meta where key='attempt'").fetchone()[0]


def append(operation_id, intent):
    conf = route()
    attempt = next_attempt()
    STATE['attempts'].append(dict(attempt=attempt, allowed=conf.get('allowed') is True,
                                  at_ns=time.time_ns()))
    STATE['invocations'][str(attempt)] = dict(attempt=attempt, operation_id=operation_id,
                                              intent=intent, terminal=False, receipt=None,
                                              error=None, started_ns=time.time_ns())
    save_state()
    if attempt == 1 and conf.get('crash') == 'before_commit':
        (ROOT / 'crash.before').write_text('before', encoding='utf-8')
        os._exit(17)
    if attempt == 1 and conf.get('delayed'):
        time.sleep(float(conf.get('gate_s', 0.08)))
    if attempt == 1 and conf.get('outcome') == 'fail':
        STATE['invocations'][str(attempt)].update(terminal=True, error='injected_failure')
        save_state()
        return dict(state='error', error_type='injected_failure')
    body = commit(attempt, operation_id, intent)
    if attempt == 1 and conf.get('crash') == 'after_commit':
        (ROOT / 'crash.after').write_text('after', encoding='utf-8')
        os._exit(17)
    STATE['invocations'][str(attempt)].update(terminal=True, receipt=body)
    save_state()
    return body


def effects(operation_id, intent):
    conf = route()
    if conf.get('query_complete') is not True:
        return dict(state='unknown', complete=False, effect_namespace='effects',
                    operation_id=operation_id, intent=intent, generation=1)
    with sqlite3.connect(DB_PATH) as db:
        rows = db.execute('select id,origin,attempt from effects where operation_id=? and intent=? '
                          'order by id', (operation_id, intent)).fetchall()
    body = dict(state='committed' if rows else 'not_committed', complete=True,
                effect_namespace='effects', operation_id=operation_id, intent=intent,
                generation=1, rows=[dict(record_id=r[0], origin=r[1], attempt=r[2]) for r in rows])
    if rows:
        body['record_id'] = rows[0][0]
    return body


def status(attempt):
    conf = route()
    entry = STATE['invocations'].get(str(attempt))
    if entry is None:
        return dict(error='unknown_attempt', attempt=attempt)
    members = []
    if conf.get('closed_registration') is True:
        members.append(dict(handle=f'root:{attempt}', parent=None, terminal=entry['terminal'],
                            error_type=entry['error'], receipt=entry['receipt']))
    return dict(root=f'root:{attempt}' if members else None, members=members, attempt=attempt,
                registration_complete=bool(conf.get('closed_registration')),
                effect_namespace='effects', launch_manifest=manifest(),
                closed_registration=bool(conf.get('closed_registration')))


def reauthorize(operation_id, intent):
    current = route()
    current['allowed'] = True
    current['revision'] = int(current.get('revision', 1)) + 1
    ROUTE_PATH.write_text(json.dumps(current), encoding='utf-8')
    STATE['reauth'].append(dict(operation_id=operation_id, intent=intent,
                                revision=current['revision'], at_ns=time.time_ns()))
    save_state()
    return dict(state='reauthorized', allowed=True, revision=current['revision'],
                operation_id=operation_id, intent=intent, generation=1,
                effect_namespace='effects')


def describe():
    current = route()
    return dict(manifest=manifest(), route=current,
                capabilities=dict(executor_handle=True,
                                  closed_registration=current.get('closed_registration') is True),
                tools=['append', 'effects', 'status', 'reauthorize', 'describe', 'drain'],
                version='r11')


def drain():
    with sqlite3.connect(DB_PATH) as db:
        rows = db.execute('select count(*) from effects').fetchone()[0]
    return dict(drained=True, invocations=len(STATE['invocations']), effects=rows)


def main():
    global ROOT, ROUTE_PATH, STATE_PATH, DB_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    args = parser.parse_args()
    ROOT = Path(args.state)
    ROUTE_PATH = ROOT / 'route.json'
    STATE_PATH = ROOT / 'state.json'
    DB_PATH = ROOT / 'effects.sqlite'
    STATE_PATH.write_text(json.dumps(STATE), encoding='utf-8')
    with sqlite3.connect(DB_PATH) as db:
        db.execute('create table if not exists effects(id integer primary key,operation_id text,'
                   'intent text,origin text,attempt integer,allowed integer)')
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        tool = request.get('tool')
        arguments = request.get('args', {})
        try:
            if tool == 'append':
                body = append(arguments['operation_id'], arguments['intent'])
            elif tool == 'effects':
                body = effects(arguments['operation_id'], arguments['intent'])
            elif tool == 'status':
                body = status(arguments['attempt'])
            elif tool == 'reauthorize':
                body = reauthorize(arguments['operation_id'], arguments['intent'])
            elif tool == 'describe':
                body = describe()
            elif tool == 'drain':
                body = drain()
            elif tool == 'close':
                print(json.dumps(dict(id=request.get('id'), ok=True, body={})), flush=True)
                return
            else:
                raise ValueError(tool)
            print(json.dumps(dict(id=request.get('id'), ok=True, body=body), ensure_ascii=False),
                  flush=True)
        except BaseException as error:
            print(json.dumps(dict(id=request.get('id'), ok=False,
                                  error=type(error).__name__ + ': ' + str(error))), flush=True)


if __name__ == '__main__':
    main()
