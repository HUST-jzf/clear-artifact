"""R3 external baseline: LangGraph checkpoint/resume around one external effect."""
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

INITIAL_TIMEOUT = 0.06
GATE_DELAY_S = 0.08


class State(TypedDict, total=False):
    done: bool
    attempt: int


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


class Store:
    def __init__(self, directory, route):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.route = route.copy()
        self.db_path = directory / 'effects.sqlite'
        with sqlite3.connect(self.db_path) as db:
            db.execute('create table effects(id integer primary key,operation_id text,intent text,'
                       'origin text,attempt integer,allowed integer)')
        self.lock = threading.RLock()
        self.next_attempt = 1
        self.last_attempt = 0
        self.writes = []
        self.attempts = []
        self.gate = threading.Event()
        self.thread = None
        self.receipt = None

    def _record_attempt(self):
        with self.lock:
            attempt = self.next_attempt
            self.next_attempt += 1
            self.last_attempt = attempt
            self.attempts.append(dict(attempt=attempt, allowed=self.route.get('allowed') is True,
                                      at_ns=time.time_ns()))
            return attempt

    def _commit(self, attempt, operation_id, intent):
        with self.lock, sqlite3.connect(self.db_path) as db:
            if self.route.get('idempotency') is True:
                row = db.execute('select id from effects where operation_id=? and intent=? '
                                 'order by id limit 1', (operation_id, intent)).fetchone()
                if row:
                    return dict(state='committed', record_id=row[0], operation_id=operation_id,
                                intent=intent, generation=1, effect_namespace='effects',
                                attempt=attempt, deduplicated=True)
            allowed = self.route.get('allowed') is True
            cur = db.execute('insert into effects(operation_id,intent,origin,attempt,allowed) '
                             'values(?,?,?,?,?)',
                             (operation_id, intent, 'original' if attempt == 1 else 'retry',
                              attempt, 1 if allowed else 0))
            self.writes.append(dict(attempt=attempt, record_id=cur.lastrowid, allowed=allowed,
                                    at_ns=time.time_ns()))
            return dict(state='committed', record_id=cur.lastrowid, operation_id=operation_id,
                        intent=intent, generation=1, effect_namespace='effects', attempt=attempt)

    def _late_commit(self, attempt, operation_id, intent):
        while not self.gate.wait(0.002):
            pass
        self.receipt = self._commit(attempt, operation_id, intent)

    def call_tool(self, operation_id, intent):
        attempt = self._record_attempt()
        if attempt == 1 and self.route.get('delayed'):
            self.thread = threading.Thread(target=self._late_commit,
                                           args=(attempt, operation_id, intent), daemon=True)
            self.thread.start()
            if not self.gate.wait(INITIAL_TIMEOUT):
                self._apply_change()
                raise TimeoutError('original effect delayed beyond caller timeout')
            self.thread.join(timeout=1)
            return self.receipt
        if attempt == 1 and self.route.get('outcome') == 'fail':
            self._apply_change()
            raise RuntimeError('injected_failure_before_commit')
        body = self._commit(attempt, operation_id, intent)
        self._apply_change()
        return body

    def _apply_change(self):
        if self.change == 'revoke' and self.route.get('allowed') is True:
            self.route['allowed'] = False
            self.route['revision'] = int(self.route.get('revision', 1)) + 1

    def drain(self):
        self.gate.set()
        if self.thread:
            self.thread.join(timeout=5)
        with sqlite3.connect(self.db_path) as db:
            rows = db.execute('select id,attempt from effects order by id').fetchall()
        return dict(rows=len(rows), effects=[dict(record_id=r[0], attempt=r[1]) for r in rows])


def run(directory, route, change, fault, seed):
    start_ns = time.perf_counter_ns()
    directory.mkdir(parents=True)
    store = Store(directory, route)
    store.change = change
    operation_id = directory.name
    intent = hashlib.sha256(b'append r3 langgraph record').hexdigest()
    errors = []
    result = None

    def call(state: State):
        receipt = store.call_tool(operation_id, intent)
        if fault == 'lost' and store.last_attempt == 1:
            raise RuntimeError('crash_after_commit_before_checkpoint')
        return {'done': True, 'attempt': store.last_attempt}

    builder = StateGraph(State)
    builder.add_node('call_tool', call)
    builder.add_edge(START, 'call_tool')
    builder.add_edge('call_tool', END)
    config = {'configurable': {'thread_id': directory.name}}
    with SqliteSaver.from_conn_string(str(directory / 'checkpoints.sqlite')) as saver:
        graph = builder.compile(checkpointer=saver)
        try:
            graph.invoke({}, config)
        except BaseException as error:
            errors.append(dict(phase='first', type=type(error).__name__, message=str(error)))
        try:
            result = graph.invoke(None, config)
        except BaseException as error:
            errors.append(dict(phase='resume', type=type(error).__name__, message=str(error)))
    drained = store.drain()
    terminal = bool(result and result.get('done'))
    rows = drained['rows']
    stale = [a for a in store.attempts if a['attempt'] > 1 and not a['allowed']]
    body = dict(case=case_id(route, change, fault), seed=seed, terminal='complete' if terminal else 'pause',
                reason='checkpoint_resume' if terminal else 'resume_failed',
                attempts=len(store.attempts), rows=rows, effects=drained['effects'],
                duplicate=rows > 1, stale_new=len(stale), errors=errors,
                route=store.route, operation_id=operation_id, intent=intent,
                elapsed_ns=time.perf_counter_ns() - start_ns)
    save(directory / 'result.json', body)
    return body


def case_id(route, change, fault):
    return f"I{int(route['idempotency'])}Q1C1G{change}F{fault}"


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True)
    parser.add_argument('--route', required=True)
    parser.add_argument('--change', required=True)
    parser.add_argument('--fault', required=True)
    parser.add_argument('--seed', type=int, default=0)
    args = parser.parse_args()
    route = json.loads(args.route)
    run(Path(args.directory), route, args.change, args.fault, args.seed)


if __name__ == '__main__':
    main()
