"""Evidence bundle sealing and semantic verification."""
import hashlib
from pathlib import Path

from .audit import audit
from .core import digest


def seal(payload):
    return dict(payload, integrity=dict(sha256=digest(payload), algorithm='sha256',
                                        authenticity='not_attested'))


def unseal(bundle):
    payload = {key: value for key, value in bundle.items() if key != 'integrity'}
    if bundle.get('integrity', {}).get('sha256') != digest(payload):
        raise ValueError('Bundle digest mismatch')
    return payload


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(bundle):
    payload = unseal(bundle)
    kind = payload.get('kind')
    if kind == 'audit_bundle':
        if audit(payload['input']) != payload['result']:
            raise ValueError('Audit semantic mismatch')
    elif kind == 'replay_bundle':
        from .replay import replay
        run = Path(payload['run'])
        for name, expected in payload.get('run_files', {}).items():
            path = run / name
            if not path.exists() or _file_sha(path) != expected:
                raise ValueError('Replay source changed: ' + name)
        if replay(run)['result'] != payload['result']:
            raise ValueError('Replay semantic mismatch')
    elif kind == 'conformance_bundle':
        from .replay import replay_many
        runs = {name: Path(path) for name, path in payload['runs'].items()}
        for name, expected in payload.get('run_files', {}).items():
            source, relative = name.split('/', 1)
            path = runs[source] / relative
            if not path.exists() or _file_sha(path) != expected:
                raise ValueError('Conformance source changed: ' + name)
        if replay_many(runs)['result'] != payload['result']:
            raise ValueError('Conformance semantic mismatch')
    elif kind == 'decision_bundle':
        from .core import decide
        state = payload['input']
        expected = decide(state['origin'], state.get('current', state.get('manifest')),
                          state['capabilities'], state['qualification'], state['events'],
                          state.get('budget', 4))
        if expected != payload['result']:
            raise ValueError('Decision semantic mismatch')
    else:
        raise ValueError('Unsupported bundle kind')
    return dict(valid=True, kind=kind, whole_program='unknown', authenticity='not_attested',
                scope='digest and semantic replay; trusted observers are still premises')
