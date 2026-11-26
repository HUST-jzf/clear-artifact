"""Unbounded inductive check of CLEAR's recovery guard with Z3.

The model is an abstraction, not the implementation. It encodes one operation with an
executor lifecycle, an effect store, a permit, a deployment manifest and the
controller's qualification/observation state.

Positive results are *inductive*: Z3 checks `J(s) and P(s) and Step(s,s') and not
(J(s') and P(s'))` over the whole state space; `unsat` means no reachable state can
violate the property. Ablations use a depth-10 unrolling to produce a concrete
counterexample trace.

Run:
    python formal/z3_model.py --output formal/z3_report.json
"""
import argparse
import json
from pathlib import Path

from z3 import And, If, Implies, Int, Not, Or, Solver, is_true, sat

PHASE = dict(idle=0, running=1, committed=2, aborted=3)
OBS = dict(none=0, empty=1, present=2, unknown=3)
FIELDS = ('phase', 'store', 'permit', 'manifest', 'qual', 'obs', 'closed', 'child',
          'attempts', 'armed', 'dup', 'stale_permit', 'stale_manifest',
          'false_complete', 'terminal')


class State:
    def __init__(self, suffix=''):
        for name in FIELDS:
            setattr(self, name, Int(name + suffix))

    def domain(self):
        return And(self.phase >= 0, self.phase <= 3,
                   self.store >= 0, self.store <= 1,
                   self.permit >= 0, self.permit <= 1,
                   self.manifest >= 0, self.manifest <= 1,
                   self.qual >= -1, self.qual <= 1,
                   self.obs >= 0, self.obs <= 3,
                   self.closed >= 0, self.closed <= 1,
                   self.child >= 0, self.child <= 1,
                   self.attempts >= 0, self.attempts <= 1,
                   self.armed >= 0, self.armed <= 1,
                   self.dup >= 0, self.dup <= 1,
                   self.stale_permit >= 0, self.stale_permit <= 1,
                   self.stale_manifest >= 0, self.stale_manifest <= 1,
                   self.false_complete >= 0, self.false_complete <= 1,
                   self.terminal >= 0, self.terminal <= 1)


class Model:
    def __init__(self, a1=True, a2=True, a3=True, a4=True):
        self.a1, self.a2, self.a3, self.a4 = a1, a2, a3, a4

    def transitions(self, s, t):
        out = []

        def add(name, guard, changes):
            eq = [getattr(t, key) == changes.get(key, getattr(s, key)) for key in FIELDS]
            out.append((name, guard, And(*eq)))

        add('start', And(s.phase == PHASE['idle'], s.terminal == 0),
            {'phase': PHASE['running']})
        add('commit_original', And(s.phase == PHASE['running'], s.store == 0),
            {'phase': PHASE['committed'], 'store': 1})
        add('fail_original', s.phase == PHASE['running'],
            {'phase': PHASE['aborted']})
        add('finish_child', s.child == 1, {'child': 0})
        late_guard = And(s.phase >= PHASE['committed'], s.store == 0, s.child == 1)
        if self.a2:
            late_guard = And(late_guard, s.closed == 0)
        add('late_commit', late_guard, {'store': 1, 'child': 0})
        add('revoke', s.permit == 1, {'permit': 0})
        add('change_manifest', s.manifest == 0, {'manifest': 1})
        wait_guard = And(s.phase >= PHASE['committed'], s.closed == 0)
        if self.a2:
            wait_guard = And(wait_guard, s.child == 0)
        add('wait', wait_guard, {'closed': 1})

        if self.a1:
            add('query_faithful', s.closed == 1,
                {'obs': If(s.store == 1, OBS['present'], OBS['empty'])})
        else:
            add('query_empty', s.closed == 1, {'obs': OBS['empty']})
            add('query_present', s.closed == 1, {'obs': OBS['present']})
            add('query_unknown', s.closed == 1, {'obs': OBS['unknown']})

        if self.a3:
            add('qualify', s.closed == 1, {'qual': s.manifest})
        else:
            add('qualify_stale_view', s.closed == 1, {'qual': 0})

        effective = s.manifest if self.a3 else 0
        admit_guard = And(s.closed == 1, s.obs == OBS['empty'], s.qual == effective,
                          s.permit == 1, s.attempts == 0, s.terminal == 0)
        write = {'attempts': 1, 'store': 1, 'obs': OBS['present'],
                 'dup': Or(s.dup == 1, s.store == 1),
                 'stale_permit': Or(s.stale_permit == 1, s.permit == 0),
                 'stale_manifest': Or(s.stale_manifest == 1, s.qual != s.manifest)}
        if self.a4:
            add('admit_retry_atomic', admit_guard, write)
        else:
            add('retry_check', admit_guard, {'armed': 1})
            add('retry_write', s.armed == 1, dict(write, armed=0))

        add('complete', And(s.obs == OBS['present'], s.terminal == 0),
            {'terminal': 1, 'false_complete': Or(s.false_complete == 1, s.store == 0)})
        add('pause', s.terminal == 0, {'terminal': 1})
        return out

    def step(self, s, t):
        return Or([And(guard, eq) for _, guard, eq in self.transitions(s, t)])

    def init(self, s):
        return And(s.phase == PHASE['idle'], s.store == 0, s.permit == 1,
                   s.manifest == 0, s.qual == -1, s.obs == OBS['none'], s.closed == 0,
                   Or(s.child == 0, s.child == 1), s.attempts == 0, s.armed == 0,
                   s.dup == 0, s.stale_permit == 0, s.stale_manifest == 0,
                   s.false_complete == 0, s.terminal == 0)

    def auxiliary(self, s):
        """J: observation validity and closure facts used by the inductive proof."""
        j = And(Implies(s.obs == OBS['empty'], s.store == 0),
                Implies(s.obs == OBS['present'], s.store == 1),
                Implies(s.obs != OBS['none'], s.closed == 1),
                Implies(s.phase == PHASE['running'], s.obs == OBS['none']),
                Implies(s.closed == 1, s.phase >= PHASE['committed']),
                Implies(s.qual != -1, s.closed == 1))
        if self.a2:
            j = And(j, Implies(s.closed == 1, s.child == 0))
        return j

    def check_inductive(self, prop):
        s, t = State(), State('_2')
        solver = Solver()
        solver.add(s.domain(), t.domain())
        solver.add(self.auxiliary(s), prop(s))
        solver.add(self.step(s, t))
        solver.add(Not(And(self.auxiliary(t), prop(t))))
        result = solver.check()
        if result == sat:
            return 'sat', self.describe(solver.model(), s, t)
        return 'unsat', None

    def bounded_search(self, depth, prop):
        """Return the shortest counterexample up to `depth` steps."""
        for bound in range(1, depth + 1):
            states = [State(f'_{i}') for i in range(bound + 1)]
            solver = Solver()
            solver.add(*[state.domain() for state in states])
            solver.add(self.init(states[0]))
            for left, right in zip(states, states[1:]):
                solver.add(self.step(left, right))
            solver.add(Or([Not(prop(state)) for state in states[1:]]))
            if solver.check() != sat:
                continue
            model = solver.model()
            last_index = bound
            fired = []
            for left, right in zip(states[:last_index], states[1:last_index + 1]):
                for name, guard, eq in self.transitions(left, right):
                    if is_true(model.eval(And(guard, eq), model_completion=True)):
                        fired.append(name)
            return 'sat', dict(trace=fired, state=self.values(model, states[last_index]),
                               depth=bound)
        return 'unsat', None

    def values(self, model, state):
        return {key: model.eval(getattr(state, key), model_completion=True).as_long()
                for key in FIELDS}

    def describe(self, model, s, t):
        fired = [name for name, guard, eq in self.transitions(s, t)
                 if is_true(model.eval(And(guard, eq), model_completion=True))]
        return dict(before=self.values(model, s), after=self.values(model, t),
                    transition=fired)


def no_dup(s):
    return s.dup == 0


def no_stale_permit(s):
    return s.stale_permit == 0


def no_stale_manifest(s):
    return s.stale_manifest == 0


def no_false_complete(s):
    return s.false_complete == 0


def safe(s):
    return And(no_dup(s), no_stale_permit(s), no_stale_manifest(s), no_false_complete(s))


def t3_impossibility():
    store1, store2, action = Int('w1_store'), Int('w2_store'), Int('action')
    solver = Solver()
    solver.add(Or(store1 == 0, store1 == 1), Or(store2 == 0, store2 == 1),
               store1 != store2, Or(action == 0, action == 1, action == 2))

    def safe_in(a, store):
        return Or(And(a == 0, store == 0), And(a == 1, store == 1), a == 2)

    def completes(a, store):
        return Or(a == 0, And(a == 1, store == 1))

    solver.add(safe_in(action, store1), safe_in(action, store2),
               completes(action, store1), completes(action, store2))
    return dict(name='T3_incomplete_evidence_impossibility',
                claim=('no single action is both safe and completing in two worlds that '
                       'share the same incomplete observation (unknown query, unobserved '
                       'closure)'),
                result=str(solver.check()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='formal/z3_report.json')
    parser.add_argument('--depth', type=int, default=10)
    args = parser.parse_args()

    report = dict(tool='z3', depth=args.depth, theorems={}, ablations={}, base={})

    all_on = Model()
    results = {
        'T1_retry_soundness': (all_on, no_dup),
        'T2_admission_atomicity': (all_on, no_stale_permit),
        'T4_requalification': (all_on, no_stale_manifest),
        'all_assumptions_safe': (all_on, safe),
    }
    for name, (model, prop) in results.items():
        result, trace = model.check_inductive(prop)
        report['theorems'][name] = dict(result=result, counterexample=trace)

    report['theorems']['T3_incomplete_evidence_impossibility'] = t3_impossibility()

    s = State()
    base = Solver()
    base.add(s.domain(), all_on.init(s), Not(And(all_on.auxiliary(s), safe(s))))
    report['base'] = dict(result=str(base.check()))

    ablations = {
        'no_A1_faithful_query': (Model(a1=False), no_dup),
        'no_A2_lifecycle_closure': (Model(a2=False), no_dup),
        'no_A3_version_binding': (Model(a3=False), no_stale_manifest),
        'no_A4_atomic_admission': (Model(a4=False), no_stale_permit),
    }
    for name, (model, prop) in ablations.items():
        result, trace = model.bounded_search(args.depth, prop)
        report['ablations'][name] = dict(result=result, counterexample=trace)

    expected = dict(
        T1=report['theorems']['T1_retry_soundness']['result'] == 'unsat',
        T2=report['theorems']['T2_admission_atomicity']['result'] == 'unsat',
        T3=report['theorems']['T3_incomplete_evidence_impossibility']['result'] == 'unsat',
        T4=report['theorems']['T4_requalification']['result'] == 'unsat',
        all_safe=report['theorems']['all_assumptions_safe']['result'] == 'unsat',
        base=report['base']['result'] == 'unsat',
        each_ablation_sat=all(item['result'] == 'sat'
                              for item in report['ablations'].values()))
    report['summary'] = dict(expected=expected,
                             status='pass' if all(expected.values()) else 'fail')
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                 encoding='utf-8')
    print(json.dumps(expected, ensure_ascii=False))
    raise SystemExit(0 if report['summary']['status'] == 'pass' else 1)


if __name__ == '__main__':
    main()
