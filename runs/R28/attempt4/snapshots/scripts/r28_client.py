"""R28 client: CLEAR and baselines over real third-party MCP servers."""
import json
import queue
import subprocess
import threading
import time

from clear_assurance import decide, digest

ENTITY = 'workflow'


class Mcp:
    def __init__(self, python, proxy, command, env, tool, mode, token, log):
        self.process = subprocess.Popen(
            [python, proxy, '--command', json.dumps(command), '--env', json.dumps(env),
             '--tool', tool, '--mode', mode, '--token', token, '--log', log],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.inbox = queue.Queue()
        self.next_id = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            self.inbox.put(message)

    def _send(self, message):
        self.process.stdin.write((json.dumps(message) + '\n').encode())
        self.process.stdin.flush()

    def request(self, method, params, timeout):
        self.next_id += 1
        identifier = self.next_id
        self._send(dict(jsonrpc='2.0', id=identifier, method=method, params=params))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f'{method}@{timeout * 1000:.0f}ms')
            try:
                message = self.inbox.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError(f'{method}@{timeout * 1000:.0f}ms')
            if message.get('id') != identifier:
                continue
            if 'error' in message:
                raise RuntimeError(json.dumps(message['error']))
            return message.get('result', {})

    def notify(self, method, params=None):
        self._send(dict(jsonrpc='2.0', method=method, params=params or {}))

    def initialize(self):
        result = self.request('initialize', dict(
            protocolVersion='2025-06-18', capabilities={},
            clientInfo=dict(name='clear-r28', version='1.0.0')), 10.0)
        self.notify('notifications/initialized')
        return result

    def call(self, name, arguments, timeout):
        result = self.request('tools/call', dict(name=name, arguments=arguments), timeout)
        blocks = result.get('content') or []
        text = blocks[0].get('text') if blocks and blocks[0].get('type') == 'text' else '{}'
        if result.get('isError'):
            raise RuntimeError(text)
        if isinstance(result.get('structuredContent'), dict):
            return result['structuredContent']
        return json.loads(text)

    def close(self):
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()


class MemoryServer:
    """@modelcontextprotocol/server-memory: appends, but de-duplicates identical text."""

    name = 'memory'
    tool = 'add_observations'

    def setup(self, mcp):
        mcp.call('create_entities', dict(entities=[dict(
            name=ENTITY, entityType='workflow', observations=[])]), 2.0)

    def effect(self, mcp, token):
        return mcp.call(self.tool, dict(observations=[
            dict(entityName=ENTITY, contents=[token])]), 0.4)

    def observe(self, mcp, token):
        graph = mcp.call('open_nodes', dict(names=[ENTITY]), 2.0)
        observations = [item for entity in graph.get('entities', [])
                        for item in entity.get('observations', [])]
        return sum(1 for item in observations if item == token)


class SqliteServer:
    """mcp-server-sqlite: plain INSERT, so every delivered write adds a row."""

    name = 'sqlite'
    tool = 'execute'

    def setup(self, mcp):
        mcp.call('execute', dict(sql='CREATE TABLE IF NOT EXISTS effect '
                                       '(id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT)'), 2.0)

    def effect(self, mcp, token):
        return mcp.call(self.tool, dict(
            sql=f"INSERT INTO effect(token) VALUES ('{token}')"), 0.4)

    def observe(self, mcp, token):
        rows = mcp.call('query', dict(
            sql=f"SELECT COUNT(*) AS n FROM effect WHERE token='{token}'"), 2.0)
        return int(rows[0]['n']) if rows else 0


class Host:
    """Content-addressed evidence: the server exposes values, not operation receipts."""

    def __init__(self, mcp, server, context, token, timeout=0.4):
        self.mcp = mcp
        self.server = server
        self.context = dict(context)
        self.token = token
        self.timeout = timeout
        self.manifest = dict(server=server.name, tool=server.tool)
        self.origin = dict(context=self.context.copy(), manifest=self.manifest,
                           namespace=server.name)
        self.capabilities = dict(executor_handle=False, closed_registration=False)
        self.initial_qualification = dict(valid=True, manifest=self.manifest, checks={},
                                          changed_dependencies=[])
        self.calls = []

    def append(self):
        started = time.monotonic()
        try:
            self.server.effect(self.mcp, self.token)
            outcome, body = 'return', dict(state='returned')
        except TimeoutError as error:
            outcome, body = 'timeout', dict(state='unknown', error=str(error))
        except RuntimeError as error:
            outcome, body = 'error', dict(state='error', error=str(error))
        self.calls.append(dict(tool=self.server.tool, outcome=outcome,
                               elapsed_ns=int((time.monotonic() - started) * 1e9)))
        return body

    def observe(self):
        started = time.monotonic()
        count = self.server.observe(self.mcp, self.token)
        self.calls.append(dict(tool='observe', outcome='return',
                               elapsed_ns=int((time.monotonic() - started) * 1e9)))
        if count:
            return dict(state='committed', record_id=count, complete=True,
                        rows=[dict(record_id=index + 1, origin='observed', attempt=1)
                              for index in range(count)],
                        effect_namespace=self.server.name, **self.context)
        return dict(state='not_committed', complete=True, rows=[],
                    effect_namespace=self.server.name, **self.context)


def run_clear(host, budget=4):
    events = []
    body = host.append()
    while True:
        decision = decide(host.origin, host.manifest, host.capabilities,
                          host.initial_qualification, events, budget)
        action, reason = decision['action'], decision['reason']
        if action in ('pause', 'complete'):
            return dict(policy='clear', terminal=action, reason=reason, events=events,
                        body=body)
        body = host.observe()
        events.append(dict(seq=len(events), context=host.context.copy(),
                           manifest=digest(host.manifest), action=action, body=body))


def run_blind_retry(host):
    events = []
    first = host.append()
    events.append(dict(action='post', phase='initial', outcome=first['state']))
    if first['state'] != 'returned':
        second = host.append()
        events.append(dict(action='retry', phase='retry', outcome=second['state']))
    observed = host.observe()
    terminal = 'complete' if observed['state'] == 'committed' else 'pause'
    return dict(policy='blind_retry', terminal=terminal,
                reason='blind_retry' if terminal == 'complete' else 'retry_unconfirmed',
                events=events, body=observed)


def run_query_retry(host):
    events = []
    first = host.append()
    events.append(dict(action='post', phase='initial', outcome=first['state']))
    observed = host.observe()
    events.append(dict(action='query', state=observed['state']))
    if observed['state'] == 'committed':
        return dict(policy='query_retry', terminal='complete', reason='query_observed',
                    events=events, body=observed)
    second = host.append()
    events.append(dict(action='retry', phase='retry', outcome=second['state']))
    observed = host.observe()
    events.append(dict(action='query', state=observed['state']))
    terminal = 'complete' if observed['state'] == 'committed' else 'pause'
    return dict(policy='query_retry', terminal=terminal,
                reason='query_then_retry' if terminal == 'complete' else 'retry_unconfirmed',
                events=events, body=observed)


def run_pause(host):
    first = host.append()
    terminal = 'complete' if first['state'] == 'returned' else 'pause'
    return dict(policy='pause', terminal=terminal,
                reason='returned' if terminal == 'complete' else 'single_pause',
                events=[dict(action='post', phase='initial', outcome=first['state'])],
                body=first)


POLICIES = dict(clear=run_clear, blind_retry=run_blind_retry,
                query_retry=run_query_retry, pause=run_pause)
SERVERS = dict(memory=MemoryServer(), sqlite=SqliteServer())
