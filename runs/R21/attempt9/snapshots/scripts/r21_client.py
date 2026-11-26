"""R21 client: the R19 controller over keep-alive connections.

Infrastructure differences from `r19_client.Client`, none of which changes what
any policy decides:

* one HTTP/1.1 connection per workflow instead of one per request. With 800
  workflows x ~25 calls the per-request variant leaves >10k sockets in TIME_WAIT
  (measured), which exhausts the Windows ephemeral port range and produces
  sporadic connect stalls unrelated to the controller;
* the fault window is 2.5 s while writes get 1.5 s, so a `late_commit` still
  times out for every policy with a 1.6x margin against infrastructure jitter;
* policy reads (`/permit`, `/ops`, `/effects`) get 2 s instead of 0.5 s;
* the end-of-workflow `GET /state` is a measurement surface (read after the
  latency window closes, never used by a policy), so it gets 5 s and up to three
  attempts.

A GET is retried once on a fresh connection when a reused socket is already dead.
A POST is never retried here: a retry could itself be the duplicate under test.
"""
import http.client
import json
import time

import r19_client as base

POST_TIMEOUT = 1.5
READ_TIMEOUT = 2.0
LATE_DELAY = 2.5
MEASURE_TIMEOUT = 5.0
MEASURE_ATTEMPTS = 3
STALE = (http.client.RemoteDisconnected, http.client.BadStatusLine,
         ConnectionResetError, ConnectionAbortedError, BrokenPipeError)


def _label(error, begin, reused):
    return '%s@%.0fms%s' % (type(error).__name__, (time.perf_counter() - begin) * 1000,
                            '/reused' if reused else '')


class Client(base.Client):
    def __init__(self, base_url):
        super().__init__(base_url)
        self.connection = None

    def close(self):
        if self.connection is not None:
            try:
                self.connection.close()
            except OSError:
                pass
            self.connection = None

    def request(self, method, path, body=None, key=None, timeout=READ_TIMEOUT):
        self.http_calls += 1
        begin = time.perf_counter()
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['Idempotency-Key'] = key
        payload = json.dumps(body).encode() if body is not None else None
        for _ in range(2):
            reused = self.connection is not None
            if not reused:
                self.connection = http.client.HTTPConnection(self.host, self.port,
                                                             timeout=timeout)
            connection = self.connection
            connection.timeout = timeout
            if connection.sock is not None:
                connection.sock.settimeout(timeout)
            try:
                connection.request(method, path, body=payload, headers=headers)
                response = connection.getresponse()
                data = response.read()
                try:
                    parsed = json.loads(data or b'{}')
                except ValueError:
                    self.close()
                    return dict(ok=False, status=response.status, body={},
                                error='bad_json:' + repr(data[:64]))
                return dict(ok=response.status < 400, status=response.status, body=parsed)
            except STALE as error:
                self.close()
                if method == 'GET' and reused:
                    continue
                return dict(ok=False, status=None, body={},
                            error=_label(error, begin, reused))
            except (OSError, http.client.HTTPException) as error:
                self.close()
                return dict(ok=False, status=None, body={},
                            error=_label(error, begin, reused))
        return dict(ok=False, status=None, body={}, error='reconnect_failed')

    def post_step(self, workflow, step, attempt, epoch, key):
        self.post_calls += 1
        body = dict(op=f'{workflow}:{step}', step=step, attempt=attempt,
                    permit_epoch=epoch, intent=base.INTENT[step])
        return self.request('POST', f'/w/{workflow}/{step}', body, key, POST_TIMEOUT)

    def state(self, workflow):
        response = None
        for _ in range(MEASURE_ATTEMPTS):
            response = self.request('GET', f'/w/{workflow}/state', timeout=MEASURE_TIMEOUT)
            if response['ok']:
                return response
        return response
