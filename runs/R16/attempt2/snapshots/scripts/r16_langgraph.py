"""R16 baseline B: LangGraph with SQLite checkpoints and node-level retries.

Configuration follows the LangGraph 1.2.16 API: one node per ticket step, a
`SqliteSaver` checkpointer per workflow, and `RetryPolicy(max_attempts=2,
initial_interval=10 ms, backoff_factor=1.0)` restricted to transport errors
(`ConnectionError`, `TimeoutError`). Idempotency key = `thread_id/node`. No
CLEAR logic is imported.
"""
import argparse
import sys
import time
import traceback
from pathlib import Path
from typing import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r16_common import (FAULTS, STEPS, ServiceClient, jitters, metrics, save,
                        workflow_id)

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

ROOT = Path(__file__).resolve().parents[1]


class State(TypedDict, total=False):
    last: str


RETRY = RetryPolicy(max_attempts=2, initial_interval=0.01, backoff_factor=1.0,
                    jitter=False, retry_on=(ConnectionError, TimeoutError))


def make_node(client, workflow, step, delay, counters):
    def call(state: State) -> State:
        time.sleep(delay)
        counters[step] += 1
        permit = client.permit(workflow)
        response = client.step(workflow, step, counters[step], int(permit.get('epoch', 1)))
        if not response['ok']:
            error = response.get('error') or 'transport'
            if error == 'TimeoutError':
                raise TimeoutError(error)
            raise ConnectionError(error)
        return {'last': step}
    return call


def run_workflow(base_url, directory, config_label, fault, seed):
    workflow = workflow_id('langgraph', config_label, fault, seed)
    client = ServiceClient(base_url)
    counters = {step: 0 for step in STEPS}
    delays = jitters(fault, seed)
    builder = StateGraph(State)
    for step, delay in zip(STEPS, delays):
        builder.add_node(step, make_node(client, workflow, step, delay, counters),
                         retry_policy=RETRY)
    builder.add_edge(START, STEPS[0])
    for left, right in zip(STEPS, STEPS[1:]):
        builder.add_edge(left, right)
    builder.add_edge(STEPS[-1], END)
    directory.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter_ns()
    terminal, errors = 'complete', []
    with SqliteSaver.from_conn_string(str(directory / 'checkpoints.sqlite')) as saver:
        graph = builder.compile(checkpointer=saver)
        try:
            graph.invoke({}, {'configurable': {'thread_id': workflow}})
        except BaseException as error:
            terminal = 'failed'
            errors.append(dict(type=type(error).__name__, message=str(error)))
    body = metrics(client, workflow, terminal, started)
    body.update(baseline='langgraph', config=config_label, fault=fault, seed=seed,
                attempts=counters, errors=errors)
    return body


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--config', required=True, choices=['idem_on', 'idem_off'])
    parser.add_argument('--seeds', default='0-19')
    parser.add_argument('--out', required=True)
    parser.add_argument('--run-root', required=True)
    args = parser.parse_args()
    if '-' in args.seeds:
        low, high = args.seeds.split('-')
        seeds = list(range(int(low), int(high) + 1))
    else:
        seeds = [int(item) for item in args.seeds.split(',') if item]
    run_root = Path(args.run_root).resolve()
    results, failures = [], []
    for fault in FAULTS:
        for seed in seeds:
            try:
                results.append(run_workflow(args.base_url, run_root / 'workflows' /
                                            workflow_id('langgraph', args.config, fault, seed),
                                            args.config, fault, seed))
            except BaseException as error:
                failures.append(dict(config=args.config, fault=fault, seed=seed,
                                     type=type(error).__name__, message=str(error),
                                     traceback=traceback.format_exc()))
    save(args.out, dict(baseline='langgraph', config=args.config, seeds=seeds,
                        tasks=results, failures=failures,
                        retry_policy=dict(max_attempts=2, initial_interval_ms=10,
                                          backoff_factor=1.0, jitter=False,
                                          retry_on=['ConnectionError', 'TimeoutError'])))


if __name__ == '__main__':
    main()
