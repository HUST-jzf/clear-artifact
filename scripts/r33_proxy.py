"""A TCP proxy that adds a fixed one-way delay, used to emulate WAN round trips.

`--delay-ms 10` adds 10 ms in each direction, i.e. a 20 ms RTT. Nothing is parsed:
the proxy forwards bytes, so the service is untouched.
"""
import argparse
import json
import socket
import threading
import time
from pathlib import Path


class Pipe(threading.Thread):
    def __init__(self, source, sink, delay):
        super().__init__(daemon=True)
        self.source, self.sink, self.delay = source, sink, delay

    def run(self):
        try:
            while True:
                data = self.source.recv(65536)
                if not data:
                    break
                if self.delay:
                    time.sleep(self.delay)
                self.sink.sendall(data)
        except OSError:
            pass
        finally:
            try:
                self.sink.shutdown(socket.SHUT_WR)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target-host', default='127.0.0.1')
    parser.add_argument('--target-port', type=int, required=True)
    parser.add_argument('--delay-ms', type=float, default=0.0)
    parser.add_argument('--ready', required=True)
    args = parser.parse_args()
    delay = args.delay_ms / 1000.0
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', 0))
    server.listen(128)
    Path(args.ready).write_text(json.dumps(dict(port=server.getsockname()[1],
                                                delay_ms=args.delay_ms)) + '\n',
                                encoding='utf-8')
    while True:
        client, _ = server.accept()
        upstream = socket.create_connection((args.target_host, args.target_port))
        Pipe(client, upstream, delay).start()
        Pipe(upstream, client, delay).start()


if __name__ == '__main__':
    main()
