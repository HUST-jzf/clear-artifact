"""Bounded explicit-state model for CLEAR's recovery guard.

This is a small, auditable abstraction, not the implementation. It enumerates
controller and environment interleavings and searches for the shortest violation of:

  S1 no duplicate effect
  S2 no write with a revoked permit or unqualified manifest
  S3 no completion without a real effect

Assumptions A1-A4 can be removed one at a time. Under A1-A4 no violation should be
reachable; each removal should expose a concrete counterexample. Run:

    python formal/model.py --output formal/report.json
"""
import argparse
import collections
import json
from dataclasses import dataclass, replace
from pathlib import Path

MAX_DEPTH = 14


@dataclass(frozen=True)
class State:
    root_done: bool = False
    children_done: bool = True
    registered: bool = True
    pending_late: bool = False
    effect: int = 0
    effect_origin: str = 'none'   # none | original | retry
    query: str = 'none'          # none | empty | present
    closed: bool = False
    seen: int = 0                # manifest version the controller has qualified
    manifest: int = 0
    permit: bool = True
    armed: bool = False
    armed_permit: bool = True
    retried: bool = False
    duplicate: bool = False
    stale: bool = False
    false_complete: bool = False
    terminal: bool = False


@dataclass(frozen=True)
class Assumptions:
    a1_faithful_effect: bool = True
    a2_lifecycle_closure: bool = True
    a3_version_binding: bool = True
    a4_atomic_admission: bool = True


SCENARIOS = {
    'plain': dict(),
    'registered_pending': dict(children_done=False, pending_late=True, registered=True),
    'unregistered_pending': dict(children_done=False, pending_late=True, registered=False),
}


def initial(scenario):
    return State(**SCENARIOS[scenario])


def environment(state):
    """Nondeterministic environment steps. Each returns (label, next_state)."""
    out = []
    if not state.root_done and state.effect == 0:
        out.append(('commit_original', replace(state, root_done=True, effect=1,
                                               effect_origin='original', query='none')))
        out.append(('fail_original', replace(state, root_done=True)))
    if state.pending_late and not state.children_done:
        out.append(('finish_child', replace(state, children_done=True)))
        if state.effect == 0:
            out.append(('late_commit', replace(state, children_done=True, effect=1,
                                               effect_origin='original', query='none')))
        elif state.effect_origin == 'retry':
            out.append(('late_commit_duplicate', replace(state, children_done=True,
                                                         duplicate=True, query='none')))
        else:
            out.append(('late_commit_same_original', replace(state, children_done=True,
                                                             query='none')))
    if state.permit:
        out.append(('revoke_permit', replace(state, permit=False, armed_permit=False)))
    if state.manifest == 0:
        out.append(('change_manifest', replace(state, manifest=1)))
    return out


def controller(state, assumptions):
    """Guard-restricted controller steps. Illegal actions are simply absent."""
    out = []
    if state.terminal:
        return out
    if not state.closed:
        closed = state.root_done and (state.children_done and state.registered
                                      if assumptions.a2_lifecycle_closure else True)
        out.append(('wait', replace(state, closed=closed)))
    if state.query == 'none' and state.closed:
        if assumptions.a1_faithful_effect:
            observed = 'present' if state.effect else 'empty'
            out.append(('query', replace(state, query=observed)))
        else:
            out.append(('query_empty', replace(state, query='empty')))
            out.append(('query_present', replace(state, query='present')))
    if assumptions.a3_version_binding:
        out.append(('qualify', replace(state, seen=state.manifest)))
    else:
        out.append(('qualify_stale_view', replace(state, seen=0)))
    effective = state.manifest if assumptions.a3_version_binding else 0
    if (not state.retried and state.closed and state.query == 'empty' and state.seen == effective):
        if assumptions.a4_atomic_admission:
            if state.permit:
                out.append(('retry', replace(state,
                                             effect=1,
                                             effect_origin='retry',
                                             duplicate=state.effect == 1,
                                             stale=state.seen != state.manifest,
                                             retried=True)))
        elif state.permit:
            out.append(('retry_check', replace(state, armed=True, armed_permit=state.permit)))
    if state.armed:
        out.append(('retry_write', replace(state,
                                           effect=1,
                                           effect_origin='retry',
                                           duplicate=state.effect == 1,
                                           stale=(not state.permit) or state.seen != state.manifest,
                                           retried=True,
                                           armed=False)))
    if state.query == 'present':
        out.append(('complete', replace(state, terminal=True, false_complete=state.effect == 0)))
    out.append(('pause', replace(state, terminal=True)))
    return out


def violations(state):
    found = []
    if state.duplicate:
        found.append('S1_duplicate')
    if state.stale:
        found.append('S2_stale_permit_or_manifest')
    if state.false_complete:
        found.append('S3_false_completion')
    return found


def explore(scenario, assumptions, max_depth=MAX_DEPTH):
    start = initial(scenario)
    queue = collections.deque([(start, [])])
    seen = {start}
    explored = 0
    while queue:
        state, trace = queue.popleft()
        explored += 1
        found = violations(state)
        if found:
            return dict(violation=found, trace=trace, states=explored)
        if len(trace) >= max_depth:
            continue
        for label, nxt in environment(state) + controller(state, assumptions):
            if nxt in seen:
                continue
            seen.add(nxt)
            queue.append((nxt, trace + [label]))
    return dict(violation=[], trace=[], states=explored)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output')
    args = parser.parse_args()
    configs = {
        'A1-A4': Assumptions(),
        'no_A1_faithful_effect': Assumptions(a1_faithful_effect=False),
        'no_A2_lifecycle_closure': Assumptions(a2_lifecycle_closure=False),
        'no_A3_version_binding': Assumptions(a3_version_binding=False),
        'no_A4_atomic_admission': Assumptions(a4_atomic_admission=False),
    }
    report = dict(max_depth=MAX_DEPTH, configs={})
    for name, assumptions in configs.items():
        report['configs'][name] = {}
        for scenario in SCENARIOS:
            report['configs'][name][scenario] = explore(scenario, assumptions)
    base = report['configs']['A1-A4']
    safe = all(not item['violation'] for item in base.values())
    each = {name: any(item['violation'] for item in result.values())
            for name, result in report['configs'].items()}
    report['summary'] = dict(safe_under_all_assumptions=safe,
                             counterexample_for_each_removed_assumption=all(
                                 each[name] for name in configs if name != 'A1-A4'),
                             has_violation=each)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + '\n', encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False))
    for name, result in report['configs'].items():
        for scenario, value in result.items():
            if value['violation']:
                print(name, scenario, value['violation'], ' / '.join(value['trace']))
    raise SystemExit(0 if safe and report['summary']['counterexample_for_each_removed_assumption'] else 1)


if __name__ == '__main__':
    main()
