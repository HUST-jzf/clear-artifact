"""R28 stdio proxy: relay MCP JSON-RPC, drop one framed response or request."""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--command', required=True, help='JSON list: node script [args]')
    parser.add_argument('--env', default='{}', help='JSON object of extra environment')
    parser.add_argument('--tool', required=True)
    parser.add_argument('--mode', required=True, choices=['drop_response', 'drop_request'])
    parser.add_argument('--token', required=True)
    parser.add_argument('--log', required=True)
    args = parser.parse_args()
    log_path = Path(args.log)
    environment = dict(os.environ, **json.loads(args.env))
    child = subprocess.Popen(json.loads(args.command), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=None, env=environment)
    write_lock = threading.Lock()
    state = dict(dropped=None)

    def emit(payload):
        with write_lock:
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()

    def upstream():
        for line in sys.stdin.buffer:
            try:
                message = json.loads(line)
            except ValueError:
                child.stdin.write(line)
                child.stdin.flush()
                continue
            params = message.get('params') or {}
            hit = (state['dropped'] is None and message.get('method') == 'tools/call'
                   and params.get('name') == args.tool
                   and args.token in json.dumps(params, ensure_ascii=False))
            if hit and args.mode == 'drop_request':
                state['dropped'] = dict(kind='request', id=message.get('id'),
                                        name=params.get('name'), at_ns=time.time_ns())
                log_path.write_text(json.dumps(state['dropped']), encoding='utf-8')
                continue
            if hit and args.mode == 'drop_response':
                state['dropped'] = dict(kind='response', id=message.get('id'),
                                        name=params.get('name'), at_ns=time.time_ns())
                log_path.write_text(json.dumps(state['dropped']), encoding='utf-8')
            child.stdin.write(line)
            child.stdin.flush()
        try:
            child.stdin.close()
        except OSError:
            pass

    def downstream():
        for line in child.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                emit(line)
                continue
            if (args.mode == 'drop_response' and state['dropped']
                    and message.get('id') == state['dropped']['id']):
                continue
            emit(line)

    reader = threading.Thread(target=downstream, daemon=True)
    reader.start()
    upstream()
    reader.join(timeout=10)
    child.terminate()
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        child.kill()


if __name__ == '__main__':
    main()
