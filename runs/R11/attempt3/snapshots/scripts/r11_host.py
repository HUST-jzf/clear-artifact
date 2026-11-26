"""R11 host: a real subprocess with a JSON-line RPC channel.

The worker is an ordinary OS process. A crash is produced by ``os._exit`` inside the
worker, so the controller observes either EOF on the pipe or a missing reply. The host
then restarts a fresh worker over the same state directory.
"""
import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from clear_assurance import closed, inspect

ROOT = Path(__file__).resolve().parents[1]
INITIAL_TIMEOUT = float(os.environ.get('R11_INITIAL_TIMEOUT', '0.06'))
WAIT_WINDOW = float(os.environ.get('R11_WAIT_WINDOW', '0.15'))
RPC_TIMEOUT = float(os.environ.get('R11_RPC_TIMEOUT', '5.0'))
CRASH_WINDOW = float(os.environ.get('R11_CRASH_WINDOW', '2.0'))


class WorkerGone(Exception):
    """The worker process disappeared while a call was in flight."""


class Worker:
    """One live worker process speaking newline-delimited JSON."""

    def __init__(self, directory):
        self.directory = directory
        self.counter = 0
        self.replies = queue.Queue()
        self.stderr = (directory / 'worker.stderr').open('a', encoding='utf-8')
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / 'scripts/r11_worker.py'), '--state', str(directory)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
            text=True, encoding='utf-8', bufsize=1)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.replies.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except (OSError, ValueError):
            pass
        finally:
            self.replies.put(None)

    def alive(self):
        return self.proc.poll() is None

    def request(self, tool, arguments, timeout):
        self.counter += 1
        request_id = self.counter
        try:
            self.proc.stdin.write(json.dumps(dict(id=request_id, tool=tool, args=arguments),
                                             ensure_ascii=False) + '\n')
            self.proc.stdin.flush()
        except (OSError, ValueError):
            raise WorkerGone(tool)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(tool)
            try:
                message = self.replies.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError(tool)
            if message is None:
                self.replies.put(None)
                raise WorkerGone(tool)
            if message.get('id') != request_id:
                continue
            if not message.get('ok'):
                return dict(state='error', error_type='tool_error', text=message.get('error'))
            return message['body']

    def close(self, graceful=True):
        if graceful and self.alive():
            try:
                self.request('close', {}, 1.0)
            except BaseException:
                pass
        if self.proc.poll() is None:
            try:
                self.proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                try:
                    self.proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
        for stream in (self.proc.stdin, self.proc.stdout):
            try:
                stream.close()
            except BaseException:
                pass
        try:
            self.stderr.close()
        except OSError:
            pass


class Host:
    def __init__(self, directory, route, patch=None):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.route_path = directory / 'route.json'
        self.route_path.write_text(json.dumps(route), encoding='utf-8')
        self.initial_route = dict(route)
        self.patch = patch
        self.context = dict(operation_id=directory.name,
                            intent=hashlib.sha256(b'append r11 crash record').hexdigest(),
                            generation=1)
        self.initial_observations = []
        self.calls = []
        self.attempt = 1
        self.origin = None
        self.current_manifest = None
        self.current_route = None
        self.capabilities = None
        self.initial_qualification = None
        self.worker = None
        self.begin_ns = None
        self.drain_result = None
        self.close_error = None
        self.crashed = False
        self.restarts = 0

    async def start(self):
        self.begin_ns = time.perf_counter_ns()
        self._spawn()
        await self.refresh()
        self.origin = dict(context=self.context.copy(), manifest=self.current_manifest,
                           namespace='effects')
        self.initial_qualification = inspect(self.origin, self.current_manifest, self.current_route)
        outcome = 'return_lost'
        try:
            body = self.worker.request('append', dict(self.context), INITIAL_TIMEOUT)
            if body.get('state') == 'error':
                outcome = 'error'
        except TimeoutError:
            outcome = 'timeout'
        except WorkerGone:
            outcome = 'lost_return'
        self._count('append', outcome)
        self.initial_observations.append(dict(action='append', phase='initial', attempt=1,
                                              outcome=outcome, timeout=INITIAL_TIMEOUT))
        if self.patch:
            current = json.loads(self.route_path.read_text(encoding='utf-8'))
            current.update(self.patch)
            self.route_path.write_text(json.dumps(current), encoding='utf-8')
        self._wait_crash()
        if self.crashed:
            # The crash is a one-shot fault: clear it before restarting, otherwise the
            # post-restart retry would crash the fresh worker again.
            current = json.loads(self.route_path.read_text(encoding='utf-8'))
            current['crash'] = None
            self.route_path.write_text(json.dumps(current), encoding='utf-8')
            self._close_worker(graceful=False)

    def _wait_crash(self):
        deadline = time.monotonic() + CRASH_WINDOW
        while time.monotonic() < deadline:
            if (self.directory / 'crash.after').exists() or \
                    (self.directory / 'crash.before').exists():
                self.crashed = True
                return
            if self.worker is not None and not self.worker.alive():
                # The process is gone but the marker was not observed; give the filesystem
                # a short grace period before concluding there was no crash.
                time.sleep(0.01)
                continue
            time.sleep(0.002)

    def _spawn(self):
        self.worker = Worker(self.directory)

    def _close_worker(self, graceful=True):
        if self.worker is not None:
            self.worker.close(graceful=graceful)
        self.worker = None

    async def ensure_alive(self):
        if not self.crashed:
            return
        self._close_worker(graceful=False)
        self._spawn()
        self.crashed = False
        self.restarts += 1
        await self.refresh()

    def _count(self, tool, outcome):
        self.calls.append(dict(tool=tool, outcome=outcome, time_ns=time.perf_counter_ns()))

    async def call(self, tool, arguments):
        if tool in ('describe', 'effects', 'status', 'drain'):
            await self.ensure_alive()
        try:
            body = self.worker.request(tool, arguments, RPC_TIMEOUT)
        except WorkerGone:
            self.crashed = True
            await self.ensure_alive()
            body = self.worker.request(tool, arguments, RPC_TIMEOUT)
        self._count(tool, 'error' if body.get('state') == 'error' else 'return')
        return body

    async def refresh(self):
        described = await self.call('describe', {})
        self.current_manifest = described['manifest']
        self.current_route = described['route']
        self.capabilities = described['capabilities']
        return described

    async def wait(self, attempt):
        last = None
        deadline = time.monotonic() + WAIT_WINDOW
        while True:
            last = await self.call('status', {'attempt': attempt})
            if last.get('root') is None:
                break
            if closed(last):
                break
            receipts = [m.get('receipt') for m in last.get('members', [])]
            if any(isinstance(r, dict) and r.get('state') == 'committed' for r in receipts):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.002)
        return last

    async def retry(self):
        await self.ensure_alive()
        try:
            body = self.worker.request('append', dict(self.context), RPC_TIMEOUT)
        except (TimeoutError, WorkerGone):
            self.crashed = not self.worker.alive()
            self._count('append', 'timeout')
            self.attempt += 1
            return dict(state='unknown', timeout=True, effect_namespace='effects',
                        **self.context)
        self._count('append', 'error' if body.get('state') == 'error' else 'return')
        self.attempt += 1
        return body

    async def action(self, action, qualification=None):
        if action == 'wait':
            return await self.wait(self.attempt)
        if action == 'query':
            return await self.call('effects', dict(operation_id=self.context['operation_id'],
                                                   intent=self.context['intent']))
        if action == 'qualify':
            return inspect(self.origin, self.current_manifest, self.current_route)
        if action == 'retry':
            await self.refresh()
            if not qualification or not qualification.get('valid') or \
                    qualification.get('manifest') != self.current_manifest:
                return dict(state='stale_qualification', effect_namespace='effects',
                            **self.context)
            return await self.retry()
        raise ValueError(action)

    async def drain(self):
        await self.ensure_alive()
        try:
            self.drain_result = await self.call('drain', {})
        except BaseException as error:
            self.drain_result = dict(drained=False, error=type(error).__name__)

    async def close(self):
        self.close_error = None
        try:
            self._close_worker(graceful=not self.crashed)
        except BaseException as error:
            self.close_error = dict(type=type(error).__name__, message=str(error))

    async def save(self):
        final_route = json.loads(self.route_path.read_text(encoding='utf-8'))
        save(self.directory / 'native.json', dict(
            context=self.context, origin=self.origin, initial_route=self.initial_route,
            initial_qualification=self.initial_qualification,
            initial_observations=self.initial_observations, attempt=self.attempt,
            calls=self.calls, capabilities=self.capabilities, drain=self.drain_result,
            close_error=self.close_error, restarts=self.restarts,
            final_manifest=self.current_manifest, final_route=final_route,
            crashed_markers=sorted(
                name for name in ('crash.after', 'crash.before')
                if (self.directory / name).exists())))


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
