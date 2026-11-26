"""Unbounded inductive checks for CLEAR's T5 and T6.

T5 (end-to-end no duplicate under A6) and T6 (fenced settlement under A2'/A4')
are encoded as symbolic transition systems.  For each configuration Z3 checks

    Inv(s) and Step(s, s') and not Inv(s')

over the whole state space.  `unsat` means the property is inductive, so it holds
for executions of arbitrary length (no depth bound).  T6 uses unbounded integer
fence numbers; T5 models two controllers, which is the minimal witness and the
case the paper's proof reduces to by symmetry.

T5 now models in-flight writes: `issue` makes a write remote-pending, and
`commit` may happen after the issuing controller crashes.  With a lease but no
handover closure this reproduces the reviewer's counterexample; with closure or
with atomic admission it is unreachable.

T6 has no direct commit on the recovery path: `write(original)` is only legal
for the initial fence and only once (`original_committed`), recovery goes
through `provisional` + `finalize`, and `finalize` checks settlement exclusion.
`t6_reviewer` replays the reviewer's sequence (allocate a higher retry fence,
then try to commit again) and reports `not_original` instead of a transition,
so the two-condition necessity argument for A2'/A4' survives.

Run with the R17 environment:
    runs/R17/env/Scripts/python.exe formal/t56_model.py --output formal/t56_report.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from z3 import And, If, Implies, Int, Not, Or, Solver, get_version_string, sat, unsat


# ---------------------------------------------------------------- T5

def t5_state(suffix: str = "") -> dict:
    return {
        "c": Int("c" + suffix),
        "s0": Int("s0" + suffix),
        "s1": Int("s1" + suffix),
        "lease": Int("lease" + suffix),
        "p0": Int("p0" + suffix),
        "p1": Int("p1" + suffix),
    }


def t5_domain(s: dict):
    return And(
        s["c"] >= 0, s["c"] <= 2,
        s["s0"] >= 0, s["s0"] <= 1,
        s["s1"] >= 0, s["s1"] <= 1,
        s["lease"] >= -1, s["lease"] <= 1,
        s["p0"] >= 0, s["p0"] <= 1,
        s["p1"] >= 0, s["p1"] <= 1,
    )


def t5_inv(s: dict, lease_on: bool = False, close_on_acquire: bool = False):
    # Safety plus the strengthening that makes the induction go through.
    # A cached "empty" observation is valid only while its controller still
    # holds the lease and has no write in flight.
    base = And(t5_domain(s), s["c"] <= 1)
    if lease_on:
        base = And(
            base,
            Implies(s["s0"] == 1, And(s["c"] == 0, s["lease"] == 0, s["p0"] == 0)),
            Implies(s["s1"] == 1, And(s["c"] == 0, s["lease"] == 1, s["p1"] == 0)),
        )
        if close_on_acquire:
            # The holder must have no in-flight write from the other controller,
            # and a pending write can only exist while nothing is committed.
            base = And(
                base,
                Implies(s["lease"] == 0, s["p1"] == 0),
                Implies(s["lease"] == 1, s["p0"] == 0),
                Implies(s["p0"] == 1, s["c"] == 0),
                Implies(s["p1"] == 1, s["c"] == 0),
                s["p0"] + s["p1"] <= 1,
            )
    return base


def t5_init(s: dict):
    return And(s["c"] == 0, s["s0"] == 0, s["s1"] == 0, s["lease"] == -1,
               s["p0"] == 0, s["p1"] == 0)


def t5_actions(s: dict, t: dict, lease_on: bool, atomic: bool,
               close_on_acquire: bool):
    same = lambda *names: And(*[t[n] == s[n] for n in names])
    acts = []

    if lease_on:
        for i in (0, 1):
            seen = "s%d" % i
            guard = [s["lease"] == -1]
            if close_on_acquire:
                guard += [s["p0"] == 0, s["p1"] == 0]
            acts.append(("acquire%d" % i, And(
                *guard, t["lease"] == i, t[seen] == 0,
                same("c", "s0", "s1", "p0", "p1"))))
            acts.append(("release%d" % i, And(
                s["lease"] == i, t["lease"] == -1, t[seen] == 0,
                same("c", "s0", "s1", "p0", "p1"))))

    for i in (0, 1):
        seen = "s%d" % i
        other = "s%d" % (1 - i)
        pend = "p%d" % i
        guard = [s[pend] == 0]
        if lease_on:
            guard.append(s["lease"] == i)
        acts.append(("query%d" % i, And(
            *guard,
            t[seen] == If(s["c"] == 0, 1, 0),
            t[other] == s[other],
            same("c", "lease", "p0", "p1"),
        )))

    for i in (0, 1):
        seen = "s%d" % i
        pend = "p%d" % i
        guard = [s[seen] == 1]
        if lease_on:
            guard.append(s["lease"] == i)
        acts.append(("issue%d" % i, And(
            *guard,
            t[pend] == 1,
            t[seen] == 0,
            same("c", "lease", "s%d" % (1 - i), "p%d" % (1 - i)),
        )))

    for i in (0, 1):
        pend = "p%d" % i
        guard = [s[pend] == 1]
        if atomic:
            guard.append(s["c"] == 0)
        acts.append(("commit%d" % i, And(
            *guard,
            t["c"] == s["c"] + 1,
            t[pend] == 0,
            same("s0", "s1", "lease", "p%d" % (1 - i)),
        )))

    for i in (0, 1):
        seen = "s%d" % i
        acts.append(("crash%d" % i, And(
            t[seen] == 0,
            t["lease"] == If(s["lease"] == i, -1, s["lease"]),
            same("c", "s%d" % (1 - i), "p0", "p1"),
        )))
    return acts


def t5_apply(state: tuple, action: str, lease_on: bool, atomic: bool,
             close_on_acquire: bool):
    """Replay one action on an explicit state, returning None if blocked."""
    c, s0, s1, lease, p0, p1 = state
    seen = {"s0": s0, "s1": s1}
    pend = {"p0": p0, "p1": p1}
    if action.startswith("acquire"):
        i = int(action[-1])
        if not lease_on or lease != -1:
            return None
        if close_on_acquire and (p0 or p1):
            return None
        lease = i
        seen["s%d" % i] = 0
    elif action.startswith("release"):
        i = int(action[-1])
        if not lease_on or lease != i:
            return None
        lease = -1
        seen["s%d" % i] = 0
    elif action.startswith("query"):
        i = int(action[-1])
        if pend["p%d" % i]:
            return None
        if lease_on and lease != i:
            return None
        seen["s%d" % i] = 1 if c == 0 else 0
    elif action.startswith("issue"):
        i = int(action[-1])
        if seen["s%d" % i] != 1:
            return None
        if lease_on and lease != i:
            return None
        pend["p%d" % i] = 1
        seen["s%d" % i] = 0
    elif action.startswith("commit"):
        i = int(action[-1])
        if not pend["p%d" % i]:
            return None
        if atomic and c != 0:
            return None
        c += 1
        pend["p%d" % i] = 0
    elif action.startswith("crash"):
        i = int(action[-1])
        seen["s%d" % i] = 0
        if lease_on and lease == i:
            lease = -1
    else:
        return None
    return (c, seen["s0"], seen["s1"], lease, pend["p0"], pend["p1"])


def t5_witness(lease_on: bool, atomic: bool, close_on_acquire: bool):
    base = (["acquire0", "query0", "issue0", "commit0"] if lease_on
            else ["query0", "issue0", "commit0"])
    st = (0, 0, 0, -1, 0, 0)
    for act in base:
        nxt = t5_apply(st, act, lease_on, atomic, close_on_acquire)
        if nxt is None:
            break
        st = nxt
    reachable = st[0]

    if lease_on:
        seq = ["acquire0", "query0", "issue0", "crash0", "acquire1", "query1",
               "issue1", "commit0", "commit1"]
    else:
        seq = ["query0", "query1", "issue0", "issue1", "commit0", "commit1"]
    st = (0, 0, 0, -1, 0, 0)
    trace = []
    blocked = None
    for act in seq:
        nxt = t5_apply(st, act, lease_on, atomic, close_on_acquire)
        if nxt is None:
            blocked = act
            break
        st = nxt
        trace.append(act)
    return reachable, trace, st[0], blocked


# ---------------------------------------------------------------- T6

T6_MODES = {
    "t6_both": (True, True),
    "t6_fence_only": (True, False),
    "t6_finalize_only": (False, True),
    "t6_neither": (False, False),
}


def t6_state(suffix: str = "") -> dict:
    return {
        "c": Int("c" + suffix),
        "cf": Int("cf" + suffix),
        "fin": Int("fin" + suffix),
        "nxt": Int("nxt" + suffix),
        "of": Int("of" + suffix),
        "ow": Int("ow" + suffix),
        "rf": Int("rf" + suffix),
        "prov": Int("prov" + suffix),
    }


def t6_domain(s: dict):
    return And(
        s["c"] >= 0, s["c"] <= 2,
        s["cf"] >= 0, s["fin"] >= 0, s["nxt"] >= 1,
        s["of"] >= 0, s["rf"] >= 0, s["prov"] >= 0,
        s["ow"] >= 0, s["ow"] <= 1,
    )


def t6_inv(s: dict):
    return And(
        t6_domain(s),
        # Safety.
        s["c"] <= 1,
        # Committed-effect bookkeeping.
        Implies(s["c"] == 0, s["cf"] == 0),
        Implies(s["c"] > 0, s["cf"] > 0),
        Implies(s["c"] > 0, s["cf"] <= s["fin"]),
        Implies(s["c"] == 1, s["cf"] == s["fin"]),
        Implies(s["c"] == 0, s["fin"] == 0),
        # Monotone, unique fences.  No upper bound on fence numbers.
        s["fin"] < s["nxt"],
        Or(s["of"] == 0, s["of"] < s["nxt"]),
        Or(s["rf"] == 0, s["rf"] < s["nxt"]),
        Implies(s["of"] == 0, s["rf"] == 0),
        Implies(s["rf"] > 0, And(s["of"] > 0, s["of"] < s["rf"])),
        Or(s["prov"] == 0, And(s["rf"] > 0, s["prov"] == s["rf"])),
        # Provenance.
        Implies(s["ow"] == 1, s["of"] > 0),
        Implies(And(s["c"] == 1, s["cf"] == s["of"]), s["ow"] == 1),
        Or(s["c"] == 0, s["cf"] == s["of"], s["cf"] == s["rf"]),
    )


def t6_init(s: dict):
    return And(
        s["c"] == 0, s["cf"] == 0, s["fin"] == 0, s["nxt"] == 1,
        s["of"] == 0, s["ow"] == 0, s["rf"] == 0, s["prov"] == 0,
    )


def t6_actions(s: dict, t: dict, enforce: bool, finalize_check: bool):
    same = lambda *names: And(*[t[n] == s[n] for n in names])
    f = Int("fence_choice")
    acts = []

    acts.append(("alloc_original", And(
        s["of"] == 0, s["rf"] == 0,
        f > s["fin"], f >= s["nxt"],
        t["of"] == f, t["nxt"] == f + 1,
        same("c", "cf", "fin", "ow", "rf", "prov"),
    )))
    acts.append(("alloc_retry", And(
        s["of"] > 0, s["rf"] == 0,
        f > s["fin"], f >= s["nxt"],
        t["rf"] == f, t["nxt"] == f + 1,
        same("c", "cf", "fin", "of", "ow", "prov"),
    )))

    acts.append(("write_original", And(
        s["ow"] == 0,
        s["of"] > 0,
        Or(Not(enforce), s["of"] > s["fin"]),
        t["c"] == s["c"] + 1,
        t["cf"] == If(s["c"] == 0, s["of"], s["cf"]),
        t["fin"] == If(s["of"] > s["fin"], s["of"], s["fin"]),
        t["ow"] == 1,
        same("nxt", "of", "rf", "prov"),
    )))

    acts.append(("stage_retry", And(
        s["rf"] > 0,
        s["prov"] == 0,
        Or(Not(enforce), s["rf"] > s["fin"]),
        t["prov"] == s["rf"],
        same("c", "cf", "fin", "nxt", "of", "ow", "rf"),
    )))

    acts.append(("finalize_retry", And(
        s["prov"] > 0,
        s["prov"] > s["fin"],
        Or(Not(finalize_check), s["c"] == 0),
        t["c"] == s["c"] + 1,
        t["cf"] == If(s["c"] == 0, s["prov"], s["cf"]),
        t["fin"] == s["prov"],
        t["prov"] == 0,
        same("nxt", "of", "ow", "rf"),
    )))

    # Recovery has no direct-commit action: a fresh retry fence cannot be used
    # with `write(original)`.  This is enforced by `original_committed(op)`.

    acts.append(("abort_retry", And(
        s["prov"] > 0,
        t["prov"] == 0,
        same("c", "cf", "fin", "nxt", "of", "ow", "rf"),
    )))
    return acts


def t6_apply(state: dict, action: str, fence=None, enforce=True, finalize_check=True):
    s = dict(state)
    if action == "alloc_original":
        if s["of"] != 0 or s["rf"] != 0 or fence <= s["fin"]:
            return None
        s["of"] = fence
        s["nxt"] = fence + 1
    elif action == "alloc_retry":
        if s["of"] == 0 or s["rf"] != 0 or fence <= s["fin"]:
            return None
        s["rf"] = fence
        s["nxt"] = fence + 1
    elif action == "write_original":
        if s["ow"] != 0 or s["of"] == 0:
            return None
        if enforce and s["of"] <= s["fin"]:
            return None
        prev = s["c"]
        s["c"] += 1
        if prev == 0:
            s["cf"] = s["of"]
        if s["of"] > s["fin"]:
            s["fin"] = s["of"]
        s["ow"] = 1
    elif action == "stage_retry":
        if s["rf"] == 0 or s["prov"] != 0:
            return None
        if enforce and s["rf"] <= s["fin"]:
            return None
        s["prov"] = s["rf"]
    elif action == "finalize_retry":
        if s["prov"] == 0 or s["prov"] <= s["fin"]:
            return None
        if finalize_check and s["c"] != 0:
            return None
        prev = s["c"]
        s["c"] += 1
        if prev == 0:
            s["cf"] = s["prov"]
        s["fin"] = s["prov"]
        s["prov"] = 0
    elif action == "abort_retry":
        if s["prov"] == 0:
            return None
        s["prov"] = 0
    else:
        return None
    return s


# ---------------------------------------------------------------- drivers

def check_inductive(state_factory, inv, action_factory):
    s = state_factory("")
    t = state_factory("_next")
    failures = []
    for name, formula in action_factory(s, t):
        solver = Solver()
        solver.add(inv(s), formula, Not(inv(t)))
        if solver.check() == sat:
            failures.append(name)
    return failures


def check_init(state_factory, inv, init) -> bool:
    s = state_factory("")
    solver = Solver()
    solver.add(init(s), Not(inv(s)))
    return solver.check() == unsat


def t6_witness(enforce: bool, finalize_check: bool):
    seqs = [
        [("alloc_original", 1), ("write_original", None), ("alloc_retry", 2),
         ("stage_retry", None), ("finalize_retry", None)],
        [("alloc_original", 1), ("alloc_retry", 2), ("stage_retry", None),
         ("finalize_retry", None), ("write_original", None)],
    ]
    best = ([], 0, None, None)
    for seq in seqs:
        st = {"c": 0, "cf": 0, "fin": 0, "nxt": 1, "of": 0, "ow": 0,
              "rf": 0, "prov": 0}
        trace = []
        blocked = None
        for act, fence in seq:
            nxt = t6_apply(st, act, fence, enforce, finalize_check)
            if nxt is None:
                blocked = act
                break
            st = nxt
            trace.append(act)
        if st["c"] > best[1]:
            best = (trace, st["c"], blocked, act)
    return best


def t6_reviewer(enforce: bool, finalize_check: bool):
    """The reviewer's fresh-fence direct commit is not a legal action.

    Recovery fences may only be used with `provisional`; `write(original)` is
    restricted to the initial fence and to one commit.  The replay stops at the
    attempted action and reports `not_original`.
    """
    st = {"c": 0, "cf": 0, "fin": 0, "nxt": 1, "of": 0, "ow": 0,
          "rf": 0, "prov": 0}
    trace = []
    for act, fence in [("alloc_original", 1), ("write_original", None),
                       ("alloc_retry", 2)]:
        st = t6_apply(st, act, fence, enforce, finalize_check)
        trace.append(act)
    return trace, st["c"], "not_original"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="formal/t56_report.json")
    args = parser.parse_args()

    report = {
        "schema": "r42_t56_unbounded_v2",
        "z3_version": get_version_string(),
        "t5": {
            "controllers": 2,
            "depth_bound": None,
            "configs": {},
        },
        "t6": {
            "fence_domain": "integers >= 0 (unbounded)",
            "depth_bound": None,
            "configs": {},
        },
    }

    t5_configs = {
        "t5_no_a6": (False, False, False),
        "t5_lease_naive": (True, False, False),
        "t5_lease_closed": (True, False, True),
        "t5_atomic_admit": (False, True, False),
    }
    for name, (lease_on, atomic, close_on_acquire) in t5_configs.items():
        failed = check_inductive(
            t5_state,
            lambda s, lo=lease_on, cl=close_on_acquire: t5_inv(s, lo, cl),
            lambda s, t, lo=lease_on, at=atomic, cl=close_on_acquire:
                t5_actions(s, t, lo, at, cl))
        init_ok = check_init(
            t5_state, lambda s, lo=lease_on, cl=close_on_acquire: t5_inv(s, lo, cl),
            t5_init)
        reachable, trace, committed, blocked = t5_witness(
            lease_on, atomic, close_on_acquire)
        report["t5"]["configs"][name] = {
            "init_satisfies_inv": init_ok,
            "inductive": "sat" if failed else "unsat",
            "safe": not failed,
            "counterexample_action": failed[0] if failed else None,
            "reachable_committed": reachable,
            "duplicate_witness": trace,
            "duplicate_committed": committed,
            "blocked_at": blocked,
        }

    for name, (enforce, finalize_check) in T6_MODES.items():
        failed = check_inductive(
            t6_state, t6_inv,
            lambda s, t, en=enforce, fc=finalize_check: t6_actions(s, t, en, fc))
        init_ok = check_init(t6_state, t6_inv, t6_init)
        trace, committed, blocked, _ = t6_witness(enforce, finalize_check)
        review_trace, review_c, review_blocked = t6_reviewer(enforce, finalize_check)
        report["t6"]["configs"][name] = {
            "init_satisfies_inv": init_ok,
            "inductive": "sat" if failed else "unsat",
            "safe": not failed,
            "counterexample_action": failed[0] if failed else None,
            "witness": trace,
            "witness_committed": committed,
            "blocked_at": blocked,
            "reviewer_sequence": review_trace,
            "reviewer_committed": review_c,
            "reviewer_blocked_at": review_blocked,
            "recovery_direct_commit": "rejected:not_original",
        }

    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(path),
        "t5": {k: v["safe"] for k, v in report["t5"]["configs"].items()},
        "t6": {k: v["safe"] for k, v in report["t6"]["configs"].items()},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
