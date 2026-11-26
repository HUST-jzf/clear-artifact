"""R7 overhead: time CLEAR's wait/active actions against simple policies."""
import json
import time
from collections import defaultdict
from pathlib import Path

from r1_anyio import Host


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


class TimedHost(Host):
    def __init__(self, directory, route, patch=None):
        super().__init__(directory, route, patch)
        self.timings = defaultdict(int)
        self.counts = defaultdict(int)
        self._nested = 0

    def _record(self, kind, started):
        self.timings[kind + '_ns'] += time.perf_counter_ns() - started
        self.counts[kind] += 1

    async def call(self, tool, arguments):
        body = await super().call(tool, arguments)
        self.counts[tool] += 1
        return body

    async def refresh(self):
        started = time.perf_counter_ns()
        body = await super().refresh()
        if not self._nested:
            self._record('active', started)
            self.counts['refresh'] += 1
        return body

    async def retry(self):
        started = time.perf_counter_ns()
        body = await super().retry()
        if not self._nested:
            self._record('active', started)
            self.counts['retry'] += 1
        return body

    async def action(self, action, qualification=None):
        started = time.perf_counter_ns()
        self._nested += 1
        try:
            body = await super().action(action, qualification)
        finally:
            self._nested -= 1
        self._record('wait' if action == 'wait' else 'active', started)
        self.counts[action] += 1
        return body

    async def drain(self):
        started = time.perf_counter_ns()
        await super().drain()
        self.timings['drain_ns'] += time.perf_counter_ns() - started
