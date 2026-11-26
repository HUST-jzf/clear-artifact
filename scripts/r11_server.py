"""R11 MCP server: real process crash before or after committing an effect."""
import argparse
import importlib.metadata
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import r1_server


def work(attempt, operation_id, intent):
    conf = r1_server.route()
    if attempt == 1 and conf.get('crash') == 'before_commit':
        (r1_server.ROOT / 'crash.before').write_text('before', encoding='utf-8')
        os._exit(17)
    if attempt == 1 and conf.get('delayed'):
        while not r1_server.GATE.exists():
            time.sleep(0.002)
    if attempt == 1 and conf.get('outcome') == 'fail':
        r1_server.finish(attempt, error='injected_failure')
        raise RuntimeError('injected_failure')
    result = r1_server.commit(attempt, operation_id, intent)
    if attempt == 1 and conf.get('crash') == 'after_commit':
        (r1_server.ROOT / 'crash.after').write_text('after', encoding='utf-8')
        os._exit(17)
    r1_server.finish(attempt, receipt=result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    parser.add_argument('--host', required=True)
    args = parser.parse_args()
    r1_server.ROOT = Path(args.state)
    r1_server.STATE_PATH = r1_server.ROOT / 'state.json'
    r1_server.ROUTE_PATH = r1_server.ROOT / 'route.json'
    r1_server.DB_PATH = r1_server.ROOT / 'effects.sqlite'
    r1_server.GATE = r1_server.ROOT / 'gate'
    r1_server.HOST_PATH = Path(args.host)
    r1_server.STATE_PATH.write_text(json.dumps(r1_server.STATE), encoding='utf-8')
    with sqlite3.connect(r1_server.DB_PATH) as db:
        db.execute('create table if not exists effects('
                   'id integer primary key,operation_id text,intent text,'
                   'origin text,attempt integer,allowed integer)')
    r1_server.MANIFEST = dict(
        adapter='mcp_stdio_fastmcp', version=importlib.metadata.version('mcp'),
        python=sys.version.split()[0],
        framework={name: r1_server.sha(module.__file__) for name, module in {
            'mcp.client.session': r1_server.mcp.client.session,
            'mcp.shared.session': r1_server.mcp.shared.session,
            'mcp.server.lowlevel.server': r1_server.mcp.server.lowlevel.server}.items()},
        worker_sha256=r1_server.sha(__file__),
        host_sha256=r1_server.sha(r1_server.HOST_PATH),
        observer_sha256=r1_server.sha(__file__),
        route_sha256=r1_server.sha(r1_server.ROUTE_PATH))
    r1_server.mcp_server.run(transport='stdio')


r1_server.work = work


if __name__ == '__main__':
    main()

