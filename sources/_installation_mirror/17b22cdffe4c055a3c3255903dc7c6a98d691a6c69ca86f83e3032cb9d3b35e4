"""CLEAR core: scoped evidence, qualification and guarded recovery decisions.

No framework imports, no scenario identifiers, no clocks and no oracle access.
"""
import hashlib
import json

VERSION = '2.0.0'
NAME = 'CLEAR'
EXPANSION = 'Change-aware Lifecycle Evidence and Admission for Recovery'
SCHEMA = 'clear-assurance/1'
SOURCE_FIELDS = ('adapter', 'version', 'python', 'framework', 'worker_sha256',
                 'host_sha256', 'observer_sha256')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def answer(action, reason, support=()):
    return dict(action=action, reason=reason, support=list(support))


def positive(body, origin):
    """A bound positive receipt for the original operation binding."""
    return (isinstance(body, dict) and body.get('state') == 'committed' and
            type(body.get('record_id')) is int and body['record_id'] > 0 and
            all(body.get(k) == v for k, v in origin['context'].items()) and
            body.get('effect_namespace') == origin['namespace'])


def closed(snapshot):
    """True only when every declared executor under the root is actually terminal."""
    members = snapshot.get('members', [])
    ids = [m.get('handle') for m in members]
    if snapshot.get('registration_complete') is not True or not members:
        return False
    root = snapshot.get('root')
    if root not in ids or len(ids) != len(set(ids)):
        return False
    byid = {m['handle']: m for m in members}
    if byid[root].get('parent') is not None:
        return False
    for member in members:
        if member.get('terminal') is not True:
            return False
        seen, node = set(), member['handle']
        while node != root:
            if node in seen or node not in byid:
                return False
            seen.add(node)
            node = byid[node].get('parent')
    return True


def inspect(origin, current, route):
    """Qualification of the current deployment against the original binding."""
    checks = {key: current.get(key) == origin['manifest'].get(key) for key in SOURCE_FIELDS}
    checks.update(known_route=route.get('mode') in ['inline', 'delegated'],
                  closed_registration=route.get('closed_registration') is True,
                  approval_allowed=route.get('allowed') is True,
                  same_effect_destination=route.get('store') == origin['namespace'])
    return dict(valid=all(checks.values()), manifest=current, checks=checks,
                changed_dependencies=[key for key in current
                                      if current.get(key) != origin['manifest'].get(key)])


def decide(origin, current, capabilities, qualification, events, budget=4,
           allow_requalification=True):
    """Choose the next action from observations only."""
    for index, event in enumerate(events):
        if event.get('seq') != index or event.get('context') != origin['context']:
            return answer('pause', 'invalid_operation_binding')
    for event in reversed(events):
        receipts = [event['body']] + [m.get('receipt', {}) for m in event['body'].get('members', [])]
        if any(positive(body, origin) for body in receipts):
            return answer('complete', 'original_or_retry_receipt', [event['seq']])
    if not allow_requalification and current != origin['manifest']:
        return answer('pause', 'manifest_changed_no_requalification')
    if events and events[-1]['action'] == 'qualify' and not events[-1]['body']['valid']:
        return answer('pause', 'destination_contract_not_qualified', [events[-1]['seq']])
    if events and events[-1]['body'].get('state') == 'stale_qualification':
        return answer('pause', 'atomic_admission_rejected', [events[-1]['seq']])
    retries = [event for event in events if event['action'] == 'retry']
    if retries:
        retry = retries[-1]
        if retry['body'].get('state') != 'accepted' or len(events) >= budget:
            return answer('pause', 'retry_unconfirmed', [retry['seq']])
        after = [event for event in events if event['seq'] > retry['seq']]
        if after and after[-1]['action'] == 'query':
            return answer('pause', 'retry_without_positive_receipt', [retry['seq'], after[-1]['seq']])
        if after and after[-1]['action'] == 'wait' and closed(after[-1]['body']):
            return answer('query', 'confirm_accepted_retry_effect', [retry['seq'], after[-1]['seq']])
        return answer('wait', 'observe_accepted_retry_lifecycle', [retry['seq']])
    if len(events) >= budget:
        return answer('pause', 'budget_exhausted')
    terms = [event for event in events
             if event['action'] == 'wait' and event['body'].get('effect_namespace') == origin['namespace']
             and event['body'].get('launch_manifest') == digest(origin['manifest']) and closed(event['body'])]
    if terms:
        term = terms[-1]
        empty = [event for event in events
                 if event['seq'] > term['seq'] and event['action'] == 'query'
                 and event['body'].get('complete') is True
                 and event['body'].get('state') == 'not_committed'
                 and event['body'].get('effect_namespace') == origin['namespace']]
        if not empty:
            return answer('query', 'original_effect_after_original_termination', [term['seq']])
        support = [term['seq'], empty[-1]['seq']]
        if qualification['manifest'] != current:
            return answer('qualify', 'rebuild_changed_destination_qualification', support)
        if not qualification['valid']:
            return answer('pause', 'destination_not_qualified', support)
        return answer('retry', 'original_closed_empty_and_current_qualified', support)
    if not capabilities.get('executor_handle') or not capabilities.get('closed_registration'):
        if events and events[-1]['action'] == 'query':
            return answer('pause', 'original_lifecycle_unavailable')
        return answer('query', 'positive_original_effect_without_lifecycle')
    if events and events[-1]['action'] == 'wait':
        return answer('query', 'check_original_effect_while_pending')
    return answer('wait', 'observe_original_lifecycle')
