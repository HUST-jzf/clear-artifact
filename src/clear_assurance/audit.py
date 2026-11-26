"""Ordinary relational coverage judgment over declared complete observations."""
import sqlite3

from .core import SCHEMA, digest

QUERY = '''SELECT e.seq, (SELECT MIN(g.seq) FROM events g
 WHERE g.kind='guard' AND g.allowed=1 AND g.resource=e.resource
 AND g.principal IS e.principal AND g.seq<e.seq) AS guard_seq
 FROM events e WHERE e.kind='effect' ORDER BY e.seq'''

CONTEXT_KEYS = ('operation_id', 'intent', 'generation', 'source_sha256', 'policy_revision')


def validate_context(context):
    if set(context) != set(CONTEXT_KEYS):
        raise ValueError('Context fields do not match schema')
    if type(context['generation']) is not int or context['generation'] < 1:
        raise ValueError('Invalid generation')
    for key in ['operation_id', 'policy_revision']:
        if not isinstance(context[key], str) or not context[key]:
            raise ValueError('Invalid ' + key)
    for key in ['intent', 'source_sha256']:
        value = context[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('Invalid ' + key)
    return context


def binding_errors(context, events):
    validate_context(context)
    errors = []
    for index, event in enumerate(events):
        if event.get('seq') != index:
            errors.append('noncontiguous_sequence:' + str(index))
        if event.get('context') != context:
            errors.append('context_mismatch:' + str(index))
    return errors


def audit(document):
    if document.get('schema') != SCHEMA or document.get('kind') != 'audit':
        raise ValueError('Not an audit envelope')
    context = document['context']
    events = document['events']
    complete = document['completeness']
    gaps = binding_errors(context, events)
    effects = [event for event in events if event.get('kind') == 'effect']
    if complete.get('effect') is not True:
        gaps.append('effect_observation_incomplete')
    if effects and complete.get('guard') is not True:
        gaps.append('guard_observation_incomplete')
    for event in events:
        if event.get('kind') not in ['guard', 'effect']:
            gaps.append('unsupported_event_kind')
        if not isinstance(event.get('resource'), str) or not event['resource']:
            gaps.append('missing_resource')
        if event.get('kind') == 'guard' and type(event.get('allowed')) is not bool:
            gaps.append('missing_guard_result')
        if effects and document.get('require_principal', True) and not isinstance(event.get('principal'), str):
            gaps.append('missing_principal')
    witnesses = []
    if gaps:
        verdict = 'unknown'
    elif not effects:
        verdict = 'no_effect'
    else:
        with sqlite3.connect(':memory:') as db:
            db.execute('create table events(seq integer,kind text,resource text,principal text,allowed integer)')
            db.executemany('insert into events values(?,?,?,?,?)',
                           [(event['seq'], event['kind'], event['resource'], event.get('principal'),
                             event.get('allowed')) for event in events])
            witnesses = [dict(effect_seq=seq, guard_seq=guard) for seq, guard in db.execute(QUERY)]
        verdict = 'covered' if all(w['guard_seq'] is not None for w in witnesses) else 'uncovered'
    return dict(schema=SCHEMA, kind='audit_result', context=context, verdict=verdict,
                witnesses=witnesses, gaps=sorted(set(gaps)), input_sha256=digest(document),
                whole_program='unknown',
                premises=['trusted observer', 'declared resource/principal identity',
                          'declared current policy and completeness'])
