"""R16 baseline A: Temporal workflow with documented activity retries.

Configuration is the one used by R3 (CLI 1.9.1 / Server 1.32.0 / SDK 1.34.0):
one activity per ticket step, `maximum_attempts=2`, constant 10 ms backoff, and
the stable idempotency key `workflow_id/step`. No CLEAR logic is imported.
"""
import argparse
import asyncio
import socket
import subprocess
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from r16_common import (FAULTS, STEPS, ServiceClient, jitters, metrics, save,
                        workflow_id)

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

TASK_QUEUE = 'r16-temporal'
PORT = 17234
MAX_ATTEMPTS = 2
ACTIVITY_TIMEOUT = timedelta(milliseconds=250)


def cli_path():
    return Path(__file__).resolve().parents[1] / 'sources/R3_temporal/cli/temporal.exe'


@activity.defn
def ticket_step(config: dict) -> dict:
    client = ServiceClient(config['base_url'])
    permit = client.permit(config['workflow'])
    response = client.step(config['workflow'], config['step'], activity.info().attempt,
                           int(permit.get('epoch', 1)))
    if not response['ok']:
        raise ApplicationError(response.get('error') or 'transport',
                               type='TransportError', non_retryable=False)
    return response['body']


@workflow.defn
class TicketFlow:
    @workflow.run
    async def run(self, config: dict) -> list:
        records = []
        for step, delay in zip(STEPS, config['jitters']):
            if delay > 0:
                await workflow.sleep(timedelta(seconds=delay))
            records.append(await workflow.execute_activity(
                ticket_step, dict(config, step=step),
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                schedule_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=MAX_ATTEMPTS,
                                         initial_interval=timedelta(milliseconds=10),
                                         backoff_coefficient=1.0)))
        return records


def wait_port(port, timeout=40.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def start_server(run_root):
    log = (run_root / 'temporal_server.log').open('w', encoding='utf-8')
    process = subprocess.Popen(
        [str(cli_path()), 'server', 'start-dev', '--headless', '--port', str(PORT),
         '--db-filename', str(run_root / 'temporal.db')],
        stdout=log, stderr=subprocess.STDOUT)
    if not wait_port(PORT):
        process.terminate()
        raise RuntimeError('temporal dev server did not open port')
    return process, log


async def campaign(base_url, config_label, seeds):
    client = await Client.connect(f'127.0.0.1:{PORT}', namespace='default')
    results, failures = [], []
    executor = ThreadPoolExecutor(max_workers=8)
    async with Worker(client, task_queue=TASK_QUEUE, workflows=[TicketFlow],
                      activities=[ticket_step], max_concurrent_activities=4,
                      activity_executor=executor):
        for fault in FAULTS:
            for seed in seeds:
                workflow_id_value = workflow_id('temporal', config_label, fault, seed)
                config = dict(base_url=base_url, workflow=workflow_id_value,
                              fault=fault, seed=seed, jitters=jitters(fault, seed))
                started = time.perf_counter_ns()
                terminal = 'complete'
                try:
                    await asyncio.wait_for(
                        client.execute_workflow(TicketFlow.run, config,
                                                id=workflow_id_value, task_queue=TASK_QUEUE),
                        timeout=30)
                except BaseException as error:
                    terminal = 'failed'
                    failures.append(dict(workflow=workflow_id_value, fault=fault,
                                         seed=seed, type=type(error).__name__,
                                         message=str(error), traceback=traceback.format_exc()))
                body = metrics(ServiceClient(base_url), workflow_id_value, terminal, started)
                body.update(baseline='temporal', config=config_label, fault=fault, seed=seed)
                results.append(body)
        await asyncio.sleep(0.2)
    return results, failures


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
    process = log = None
    try:
        process, log = start_server(run_root)
        results, failures = asyncio.run(campaign(args.base_url, args.config, seeds))
        save(args.out, dict(baseline='temporal', config=args.config, seeds=seeds,
                            tasks=results, failures=failures,
                            retry_policy=dict(maximum_attempts=MAX_ATTEMPTS,
                                              initial_interval_ms=10,
                                              backoff_coefficient=1.0),
                            start_to_close_timeout_ms=250, port=PORT))
    finally:
        if process:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
        if log:
            log.close()


if __name__ == '__main__':
    main()
