"""Deterministic replay of frozen recovery evidence through the packaged decision function."""
import hashlib
import json
from pathlib import Path

from .core import SCHEMA, decide


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tasks(run):
    for directory in sorted(Path(run).iterdir()):
        if directory.is_dir() and (directory / 'result.json').exists() and (directory / 'native.json').exists():
            yield directory


def replay(run, budget=4, methods=('clear', 'spg')):
    """Recompute every recorded decision from the same observation prefix.

    Only CLEAR tasks are replayed. ``clear`` is the released name; ``spg`` is the
    frozen pre-1.0 identifier and is accepted through an explicit alias so historical
    evidence is never rewritten. Baseline tasks use different single-mechanism
    controllers and are evidence, not instances of this decision function. Supported
    evidence is the U03/U04/U05 schema; unsupported runs are rejected rather than guessed.
    """
    run = Path(run)
    tasks, steps_total, mismatches, files = [], 0, [], {}
    for directory in _tasks(run):
        result = read(directory / 'result.json')
        if methods and result.get('method') not in methods:
            continue
        native = read(directory / 'native.json')
        origin = result.get('origin') or native.get('origin')
        capabilities = native.get('capabilities')
        if not capabilities:
            route = native.get('initial_route', {})
            capabilities = dict(executor_handle=True,
                                closed_registration=route.get('closed_registration') is True)
        events = result.get('events', [])
        steps = result.get('steps', [])
        if origin is None or capabilities is None:
            continue
        for name in ['result.json', 'native.json']:
            files[f'{directory.name}/{name}'] = sha(directory / name)
        local = []
        for index, step in enumerate(steps):
            if 'qualification' not in step:
                raise ValueError('Unsupported run format: step has no qualification')
            manifest = step.get('current_manifest', step.get('manifest'))
            prefix = events[:step['observation_count']]
            expected = decide(origin, manifest, capabilities, step['qualification'], prefix, budget)
            steps_total += 1
            if expected != step['decision']:
                local.append(dict(step=index, expected=expected, recorded=step['decision']))
            if step['observation_count'] < len(events):
                acted = events[step['observation_count']]['action']
                if step['decision']['action'] != acted:
                    local.append(dict(step=index, expected_action=step['decision']['action'],
                                      recorded_action=acted))
        if steps and steps[-1]['observation_count'] != len(events):
            local.append(dict(step=len(steps) - 1, expected_action='terminal',
                              recorded_action='missing_terminal'))
        mismatches.extend(dict(task=directory.name, **item) for item in local)
        tasks.append(dict(task=directory.name, method=result.get('method'),
                          terminal=result.get('terminal'), steps=len(steps),
                          actions=len(events), matched=not local))
    return dict(run=str(run), files=files,
                result=dict(schema=SCHEMA, kind='replay_result', tasks=tasks,
                            tasks_total=len(tasks), steps_total=steps_total,
                            mismatches=mismatches, matched=not mismatches))


def replay_many(runs, budget=4, methods=('clear', 'spg')):
    """Replay several frozen runs and return one conformance result.

    ``runs`` maps a source name (e.g. ``langchain``) to a run directory. Paths and
    per-file hashes are retained so a sealed bundle can be re-verified later.
    """
    sources, files, mismatches = [], {}, []
    for name in sorted(runs):
        value = replay(runs[name], budget, methods)
        result = value['result']
        sources.append(dict(source=name, run=value['run'], tasks=result['tasks'],
                            tasks_total=result['tasks_total'],
                            steps_total=result['steps_total'],
                            mismatches=result['mismatches'], matched=result['matched']))
        for relative, digest in value['files'].items():
            files[f'{name}/{relative}'] = digest
        mismatches.extend(dict(source=name, **item) for item in result['mismatches'])
    return dict(runs={name: str(Path(path).resolve()) for name, path in runs.items()}, files=files,
                result=dict(schema=SCHEMA, kind='conformance_result', sources=sources,
                            tasks_total=sum(item['tasks_total'] for item in sources),
                            steps_total=sum(item['steps_total'] for item in sources),
                            mismatches=mismatches, matched=not mismatches))
