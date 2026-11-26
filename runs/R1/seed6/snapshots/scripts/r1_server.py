"""R1 MCP server: capability-space source with idempotency, query and lifecycle toggles."""
import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

import anyio
import anyio.to_thread
import mcp
import mcp.client.session
import mcp.server.lowlevel.server
import mcp.shared.session
from mcp.server.fastmcp import FastMCP

ROOT = None
STATE_PATH = None
ROUTE_PATH = None
DB_PATH = None
GATE = None
GATE_DELAY_S = float(os.environ.get('R1_GATE_DELAY_S', '0.08'))
HOST_PATH = None
LOCK = threading.RLock()
STATE = {'invocations': {}, 'writes': [], 'attempts': [], 'reauth': []}
MANIFEST = {}

mcp_server = FastMCP('clear-r1-capability-source')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def route():
    return json.loads(ROUTE_PATH.read_text(encoding='utf-8'))


def save_state():
    tmp = STATE_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(STATE, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    os.replace(tmp, STATE_PATH)


def manifest():
    return dict(MANIFEST, route_sha256=sha(ROUTE_PATH))


def open_gate():
    try:
        GATE.write_text('open', encoding='utf-8')
    except OSError:
        pass


def claim(operation_id, intent):
    with LOCK:
        attempt = int(STATE.get('next_attempt', 1))
        STATE['next_attempt'] = attempt + 1
        STATE['invocations'][str(attempt)] = dict(attempt=attempt, operation_id=operation_id,
                                                  intent=intent, terminal=False, receipt=None,
                                                  error=None, started_ns=time.time_ns(),
                                                  launch_manifest=digest(manifest()))
        save_state()
        return attempt


def finish(attempt, error=None, receipt=None):
    with LOCK:
        entry = STATE['invocations'][str(attempt)]
        entry['terminal'] = True
        entry['error'] = error
        entry['receipt'] = receipt
        save_state()


def receipt(attempt, rid, operation_id, intent, deduplicated=False):
    return dict(state='committed', record_id=rid, operation_id=operation_id, intent=intent,
                generation=1, effect_namespace='effects', attempt=attempt,
                deduplicated=deduplicated)


def commit(attempt, operation_id, intent):
    conf = route()
    with LOCK, sqlite3.connect(DB_PATH) as db:
        if conf.get('idempotency') is True:
            row = db.execute('select id,origin,attempt from effects where operation_id=? and intent=? '
                             'order by id limit 1', (operation_id, intent)).fetchone()
            if row is not None:
                return receipt(attempt, row[0], operation_id, intent, deduplicated=True)
        allowed = conf.get('allowed') is True
        cur = db.execute('insert into effects(operation_id,intent,origin,attempt,allowed) '
                         'values(?,?,?,?,?)', (operation_id, intent, 'original' if attempt == 1 else 'retry',
                                               attempt, 1 if allowed else 0))
        rid = cur.lastrowid
        STATE['writes'].append(dict(attempt=attempt, origin='original' if attempt == 1 else 'retry',
                                    record_id=rid, allowed=allowed, at_ns=time.time_ns()))
        save_state()
    return receipt(attempt, rid, operation_id, intent)


def work(attempt, operation_id, intent):
    conf = route()
    if attempt == 1 and conf.get('delayed'):
        while not GATE.exists():
            time.sleep(0.002)
    if attempt == 1 and conf.get('outcome') == 'fail':
        finish(attempt, error='injected_failure')
        raise RuntimeError('injected_failure')
    result = commit(attempt, operation_id, intent)
    if attempt == 1 and conf.get('outcome') == 'commit_error':
        finish(attempt, error='injected_commit_error', receipt=result)
        raise RuntimeError('injected_commit_error_after_commit')
    finish(attempt, receipt=result)
    return result


async def invoke(operation_id, intent):
    attempt = claim(operation_id, intent)
    conf = route()
    with LOCK:
        STATE['attempts'].append(dict(attempt=attempt, allowed=conf.get('allowed') is True,
                                      at_ns=time.time_ns()))
        save_state()
    if attempt == 1 and conf.get('delayed'):
        threading.Timer(GATE_DELAY_S, open_gate).start()
    return await anyio.to_thread.run_sync(work, attempt, operation_id, intent,
                                          abandon_on_cancel=bool(conf.get('abandon_on_cancel')))


@mcp_server.tool()
async def append(operation_id: str, intent: str) -> dict:
    """Append one effect according to the deployed capability profile."""
    return await invoke(operation_id, intent)


@mcp_server.tool()
async def effects(operation_id: str, intent: str) -> dict:
    conf = route()
    if conf.get('query_complete') is not True:
        return dict(state='unknown', complete=False, effect_namespace='effects',
                    operation_id=operation_id, intent=intent, generation=1)
    with LOCK, sqlite3.connect(DB_PATH) as db:
        rows = db.execute('select id,origin,attempt from effects where operation_id=? and intent=? '
                          'order by id', (operation_id, intent)).fetchall()
    body = dict(state='committed' if rows else 'not_committed', complete=True,
                effect_namespace='effects', operation_id=operation_id, intent=intent, generation=1,
                rows=[dict(record_id=row[0], origin=row[1], attempt=row[2]) for row in rows])
    if rows:
        body['record_id'] = rows[0][0]
    return body


@mcp_server.tool()
async def status(attempt: int) -> dict:
    conf = route()
    with LOCK:
        entry = STATE['invocations'].get(str(attempt))
        if entry is None:
            return dict(error='unknown_attempt', attempt=attempt)
        members = []
        if conf.get('closed_registration') is True:
            members.append(dict(handle=f'root:{attempt}', parent=None, terminal=entry['terminal'],
                                error_type=entry['error'], receipt=entry['receipt']))
        return dict(root=f'root:{attempt}' if members else None, members=members, attempt=attempt,
                    registration_complete=bool(conf.get('closed_registration')),
                    effect_namespace='effects', launch_manifest=entry['launch_manifest'],
                    closed_registration=bool(conf.get('closed_registration')))


@mcp_server.tool()
async def reauthorize(operation_id: str, intent: str) -> dict:
    with LOCK:
        current = route()
        current['allowed'] = True
        current['revision'] = int(current.get('revision', 1)) + 1
        ROUTE_PATH.write_text(json.dumps(current), encoding='utf-8')
        STATE['reauth'].append(dict(operation_id=operation_id, intent=intent,
                                    revision=current['revision'], at_ns=time.time_ns()))
        save_state()
    return dict(state='reauthorized', allowed=True, revision=current['revision'],
                operation_id=operation_id, intent=intent, generation=1, effect_namespace='effects')


@mcp_server.tool()
async def describe() -> dict:
    current = route()
    return dict(manifest=manifest(), route=current,
                capabilities=dict(executor_handle=True,
                                  closed_registration=current.get('closed_registration') is True),
                tools=['append', 'effects', 'status', 'reauthorize', 'describe', 'drain'],
                version=importlib.metadata.version('mcp'))


@mcp_server.tool()
async def drain() -> dict:
    GATE.write_text('open', encoding='utf-8')
    limit = time.monotonic() + 5
    while time.monotonic() < limit:
        with LOCK:
            pending = [entry for entry in STATE['invocations'].values() if not entry['terminal']]
        if not pending:
            break
        await anyio.sleep(0.005)
    with LOCK, sqlite3.connect(DB_PATH) as db:
        rows = db.execute('select count(*) from effects').fetchone()[0]
    return dict(drained=True, invocations=len(STATE['invocations']), effects=rows,
                terminal=not pending)


def main():
    global ROOT, STATE_PATH, ROUTE_PATH, DB_PATH, GATE, HOST_PATH, MANIFEST
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    parser.add_argument('--host', required=True)
    args = parser.parse_args()
    ROOT = Path(args.state)
    STATE_PATH = ROOT / 'state.json'
    ROUTE_PATH = ROOT / 'route.json'
    DB_PATH = ROOT / 'effects.sqlite'
    GATE = ROOT / 'gate'
    HOST_PATH = Path(args.host)
    STATE_PATH.write_text(json.dumps(STATE), encoding='utf-8')
    with sqlite3.connect(DB_PATH) as db:
        db.execute('create table effects(id integer primary key,operation_id text,intent text,'
                   'origin text,attempt integer,allowed integer)')
    MANIFEST = dict(
        adapter='mcp_stdio_fastmcp', version=importlib.metadata.version('mcp'),
        python=sys.version.split()[0],
        framework={name: sha(module.__file__) for name, module in {
            'mcp.client.session': mcp.client.session,
            'mcp.shared.session': mcp.shared.session,
            'mcp.server.lowlevel.server': mcp.server.lowlevel.server}.items()},
        worker_sha256=sha(__file__), host_sha256=sha(HOST_PATH), observer_sha256=sha(__file__),
        route_sha256=sha(ROUTE_PATH))
    mcp_server.run(transport='stdio')


if __name__ == '__main__':
    main()
