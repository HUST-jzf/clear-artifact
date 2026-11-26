"""Installable CLEAR CLI. Outputs are new files; existing evidence is never overwritten."""
import argparse
import json
import sys
from pathlib import Path

from . import VERSION
from .audit import audit
from .bundle import seal, verify
from .core import SCHEMA, decide
from .replay import replay, replay_many


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(prog='clear-assure')
    parser.add_argument('--version', action='version', version=VERSION)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ['audit', 'decide', 'verify']:
        command = sub.add_parser(name)
        command.add_argument('--input', required=True)
        command.add_argument('--output')
    command = sub.add_parser('replay')
    command.add_argument('--run', required=True)
    command.add_argument('--output')
    command.add_argument('--budget', type=int, default=4)
    command = sub.add_parser('conformance')
    command.add_argument('--input', required=True)
    command.add_argument('--output')
    args = parser.parse_args()
    try:
        if args.command == 'audit':
            document = read(args.input)
            result = seal(dict(schema=SCHEMA, kind='audit_bundle', input=document,
                               result=audit(document)))
            summary = result['result']
        elif args.command == 'decide':
            state = read(args.input)
            decision = decide(state['origin'], state.get('current', state.get('manifest')),
                              state['capabilities'], state['qualification'], state['events'],
                              state.get('budget', 4))
            result = seal(dict(schema=SCHEMA, kind='decision_bundle', input=state,
                               result=decision))
            summary = decision
        elif args.command == 'replay':
            value = replay(args.run, args.budget)
            result = seal(dict(schema=SCHEMA, kind='replay_bundle', run=value['run'],
                               run_files=value['files'], result=value['result']))
            summary = dict(tasks_total=value['result']['tasks_total'],
                           steps_total=value['result']['steps_total'],
                           matched=value['result']['matched'],
                           mismatches=value['result']['mismatches'][:5])
        elif args.command == 'conformance':
            config_path = Path(args.input).resolve()
            config = read(config_path)
            runs = {name: (config_path.parent / path if not Path(path).is_absolute() else Path(path))
                    for name, path in config['runs'].items()}
            methods = tuple(config.get('methods', ['clear', 'spg']))
            value = replay_many(runs, config.get('budget', 4), methods)
            result = seal(dict(schema=SCHEMA, kind='conformance_bundle', runs=value['runs'],
                               run_files=value['files'], result=value['result']))
            summary = dict(tasks_total=value['result']['tasks_total'],
                           steps_total=value['result']['steps_total'],
                           matched=value['result']['matched'],
                           sources=[dict(source=item['source'],
                                         tasks=item['tasks_total'],
                                         steps=item['steps_total'],
                                         matched=item['matched'])
                                    for item in value['result']['sources']],
                           mismatches=value['result']['mismatches'][:5])
        else:
            summary = verify(read(args.input))
            result = None
        if args.output and result is not None:
            save_new(args.output, result)
        print(json.dumps(summary, ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps(dict(error=type(error).__name__, message=str(error)),
                         ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
