import json
import tempfile
import unittest
from pathlib import Path

from clear_assurance import audit, closed, decide, digest, inspect, positive, replay, replay_many

CONTEXT = dict(operation_id='op', intent='a' * 64, generation=1)
MANIFEST = dict(adapter='test', version='1', python='3.13', framework={'m': 'b' * 64},
                worker_sha256='c' * 64, host_sha256='d' * 64, observer_sha256='e' * 64)
ROUTE = dict(mode='inline', closed_registration=True, allowed=True, store='effects')
ORIGIN = dict(context=CONTEXT, manifest=MANIFEST, namespace='effects')
QUALIFIED = inspect(ORIGIN, MANIFEST, ROUTE)


def event(seq, action, body, manifest=MANIFEST):
    return dict(seq=seq, context=CONTEXT, manifest=digest(manifest), action=action, body=body)


def terminal(attempt=1):
    return dict(root=f'root:{attempt}', members=[dict(handle=f'root:{attempt}', parent=None,
                                                      terminal=True, error_type=None, receipt=None)],
                attempt=attempt, registration_complete=True, effect_namespace='effects',
                launch_manifest=digest(MANIFEST))


def empty():
    return dict(state='not_committed', complete=True, effect_namespace='effects', **CONTEXT)


def receipt():
    return dict(state='committed', record_id=1, effect_namespace='effects', **CONTEXT)


class CoreTests(unittest.TestCase):
    def test_positive_requires_binding(self):
        self.assertTrue(positive(receipt(), ORIGIN))
        self.assertFalse(positive(dict(receipt(), generation=2), ORIGIN))
        self.assertFalse(positive(dict(receipt(), record_id=0), ORIGIN))

    def test_closed_rejects_pending_child(self):
        body = terminal()
        body['members'].append(dict(handle='child:1:1', parent='root:1', terminal=False,
                                    error_type=None, receipt=None))
        self.assertFalse(closed(body))
        body['members'][1]['terminal'] = True
        self.assertTrue(closed(body))

    def test_empty_observations_wait(self):
        decision = decide(ORIGIN, MANIFEST, dict(executor_handle=True, closed_registration=True),
                          QUALIFIED, [])
        self.assertEqual(decision['action'], 'wait')
        self.assertEqual(decision['reason'], 'observe_original_lifecycle')

    def test_receipt_completes(self):
        decision = decide(ORIGIN, MANIFEST, dict(executor_handle=True, closed_registration=True),
                          QUALIFIED, [event(0, 'wait', dict(terminal(), members=[
                              dict(handle='root:1', parent=None, terminal=True,
                                   error_type=None, receipt=receipt())]))])
        self.assertEqual(decision['action'], 'complete')

    def test_retry_requires_closure_empty_and_qualification(self):
        events = [event(0, 'wait', terminal()), event(1, 'query', empty())]
        decision = decide(ORIGIN, MANIFEST, dict(executor_handle=True, closed_registration=True),
                          QUALIFIED, events)
        self.assertEqual(decision['action'], 'retry')
        changed = dict(MANIFEST, route_sha256='f' * 64)
        decision = decide(ORIGIN, changed, dict(executor_handle=True, closed_registration=True),
                          QUALIFIED, events)
        self.assertEqual(decision['action'], 'qualify')
        invalid = inspect(ORIGIN, changed, dict(ROUTE, allowed=False))
        events.append(event(2, 'qualify', invalid))
        decision = decide(ORIGIN, changed, dict(executor_handle=True, closed_registration=True),
                          QUALIFIED, events)
        self.assertEqual(decision['action'], 'pause')
        self.assertEqual(decision['reason'], 'destination_contract_not_qualified')

    def test_audit_covered(self):
        document = dict(schema='clear-assurance/1', kind='audit',
                        context=dict(operation_id='op', intent='a' * 64, generation=1,
                                     source_sha256='b' * 64, policy_revision='r1'),
                        completeness=dict(guard=True, effect=True),
                        events=[dict(seq=0, context=dict(operation_id='op', intent='a' * 64,
                                                         generation=1, source_sha256='b' * 64,
                                                         policy_revision='r1'),
                                     kind='guard', resource='r', principal='p', allowed=True),
                                dict(seq=1, context=dict(operation_id='op', intent='a' * 64,
                                                         generation=1, source_sha256='b' * 64,
                                                         policy_revision='r1'),
                                     kind='effect', resource='r', principal='p')])
        self.assertEqual(audit(document)['verdict'], 'covered')

    def test_replay_synthetic(self):
        body = dict(terminal(), members=[dict(handle='root:1', parent=None, terminal=True,
                                              error_type=None, receipt=receipt())])
        events = [event(0, 'wait', body)]
        caps = dict(executor_handle=True, closed_registration=True)
        steps = []
        for count in range(2):
            decision = decide(ORIGIN, MANIFEST, caps, QUALIFIED, events[:count])
            steps.append(dict(observation_count=count, current_manifest=MANIFEST,
                              qualification=QUALIFIED, decision=decision))
        with tempfile.TemporaryDirectory() as root:
            task = Path(root) / 'T01_clear'
            task.mkdir()
            (task / 'native.json').write_text(json.dumps(dict(origin=ORIGIN, capabilities=caps)))
            (task / 'result.json').write_text(json.dumps(dict(method='clear', origin=ORIGIN,
                                                              terminal='complete', events=events,
                                                              steps=steps)))
            result = replay(root)['result']
            self.assertTrue(result['matched'], result['mismatches'])
            self.assertEqual(result['tasks_total'], 1)
            self.assertEqual(result['steps_total'], 2)

    def test_legacy_alias_and_multi_run(self):
        body = dict(terminal(), members=[dict(handle='root:1', parent=None, terminal=True,
                                              error_type=None, receipt=receipt())])
        events = [event(0, 'wait', body)]
        caps = dict(executor_handle=True, closed_registration=True)
        steps = [dict(observation_count=count, current_manifest=MANIFEST, qualification=QUALIFIED,
                      decision=decide(ORIGIN, MANIFEST, caps, QUALIFIED, events[:count]))
                 for count in range(2)]
        with tempfile.TemporaryDirectory() as root:
            runs = {}
            for name in ['legacy', 'current']:
                directory = Path(root) / name / 'T01'
                directory.mkdir(parents=True)
                (directory / 'native.json').write_text(json.dumps(dict(origin=ORIGIN,
                                                                       capabilities=caps)))
                (directory / 'result.json').write_text(json.dumps(dict(
                    method='spg' if name == 'legacy' else 'clear', origin=ORIGIN,
                    terminal='complete', events=events, steps=steps)))
                runs[name] = Path(root) / name
            result = replay_many(runs)['result']
            self.assertTrue(result['matched'], result['mismatches'])
            self.assertEqual(result['tasks_total'], 2)
            self.assertEqual(result['steps_total'], 4)


if __name__ == '__main__':
    unittest.main()
