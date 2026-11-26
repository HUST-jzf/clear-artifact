"""Run R28: two real third-party MCP servers behind a lossy stdio proxy."""
import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import r28_client

SERVERS = {
    'memory': dict(
        script=ROOT / ('sources/R28_memory_server/node_modules/@modelcontextprotocol/'
                       'server-memory/dist/index.js'),
        sources=['sources/R28_memory_server/package.json',
                 'sources/R28_memory_server/package-lock.json'],
        version='2.0.0'),
    'sqlite': dict(
        script=ROOT / 'sources/R28_sqlite_server/node_modules/mcp-server-sqlite/dist/cli.js',
        sources=['sources/R28_sqlite_server/package.json',
                 'sources/R28_sqlite_server/package-lock.json'],
        version='0.0.2'),
}
FAULTS = ['lost_response', 'lost_before_effect']
POLICIES = ['clear', 'blind_retry', 'query_retry', 'pause']
SEEDS = list(range(1, 21))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def task(run, server_name, fault, policy, seed, python):
    server = SERVERS[server_name]
    name = f'{server_name}_{fault}_{policy}_s{seed}'
    directory = run / name
    directory.mkdir(parents=True)
    token = f'effect:{server_name}:{fault}:{policy}:s{seed}'
    context = dict(operation_id=name,
                   intent=hashlib.sha256(b'one effect').hexdigest(),
                   generation=1)
    if server_name == 'memory':
        command = ['node', str(server['script'])]
        environment = {'MEMORY_FILE_PATH': str(directory / 'memory.jsonl')}
    else:
        command = ['node', str(server['script']), '--db', str(directory / 'store.db')]
        environment = {'SQLITE_DB_PATH': str(directory / 'store.db')}
    started = time.perf_counter_ns()
    mcp = r28_client.Mcp(python, str(ROOT / 'scripts/r28_proxy.py'), command, environment,
                         r28_client.SERVERS[server_name].tool,
                         'drop_response' if fault == 'lost_response' else 'drop_request',
                         token, str(directory / 'proxy.json'))
    adapter = r28_client.SERVERS[server_name]
    host = r28_client.Host(mcp, adapter, context, token)
    try:
        mcp.initialize()
        adapter.setup(mcp)
        result = r28_client.POLICIES[policy](host)
    finally:
        mcp.close()
    result.update(server=server_name, fault=fault, policy=policy, seed=seed, token=token,
                  context=context, calls=host.calls,
                  elapsed_ns=time.perf_counter_ns() - started)
    save(directory / 'result.json', result)
    return dict(name=name, server=server_name, fault=fault, policy=policy, seed=seed,
                terminal=result['terminal'], reason=result['reason'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    run = ROOT / 'runs' / 'R28' / args.attempt
    run.mkdir(parents=True, exist_ok=False)
    node = shutil.which('node')
    if node is None:
        raise SystemExit('node not found')
    node_version = subprocess.run([node, '--version'], capture_output=True,
                                  text=True).stdout.strip()
    names = ['docs/R28_third_party_services_protocol.md', 'scripts/r28_proxy.py',
             'scripts/r28_client.py', 'scripts/run_r28.py', 'scripts/verify_r28.py']
    for server in SERVERS.values():
        names += server['sources']
    hashes = {}
    for name in names:
        src, dest = ROOT / name, run / 'snapshots' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        hashes[name] = sha(src)
    save(run / 'freeze.json', dict(
        files=hashes, faults=FAULTS, policies=POLICIES, seeds=SEEDS, node=node_version,
        servers={name: dict(version=server['version'], entry_sha256=sha(server['script']))
                 for name, server in SERVERS.items()},
        target_calls_before_freeze=0, python=sys.executable,
        python_version=platform.python_version(), created_ns=time.time_ns()))
    tasks, failures = [], []
    for server_name in SERVERS:
        for fault in FAULTS:
            for policy in POLICIES:
                for seed in SEEDS:
                    try:
                        tasks.append(task(run, server_name, fault, policy, seed, sys.executable))
                    except BaseException as error:
                        failures.append(dict(server=server_name, fault=fault, policy=policy,
                                             seed=seed, type=type(error).__name__,
                                             message=str(error),
                                             traceback=traceback.format_exc()))
    save(run / 'completion.json', dict(tasks=tasks, failures=failures, node=node_version))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
