# R17 machine-checked formal model protocol (preregistered)

2026-10-21. This protocol was frozen before the main result was produced. Its
goal is to upgrade the R6 bounded pilot to an **unbounded inductive check** and
provide executable machine evidence for T1-T4. The tool is Z3 5.3.1 (the
`z3-solver` wheel, installed offline).

## 1. Model

State of a single operation:

| Variable | Values | Meaning |
|---|---|---|
| `phase` | idle / running / committed / aborted | executor lifecycle |
| `store` | empty / effect | whether the operation's effect exists in the store |
| `permit` | valid / revoked | current permit |
| `manifest` | m0 / m1 | destination version |
| `qual` | none / m0 / m1 | last qualification recorded by the controller |
| `obs` | none / empty / present / unknown | last effect observation |
| `closed` | 0 / 1 | whether the controller observed lifecycle closure |
| `child` | 0 / 1 | whether a registered child executor is still running |
| `attempts` | 0 / 1 | whether a retry has happened |
| `armed` | 0 / 1 | intermediate "checked but not written" state under non-atomic admission |
| `dup` / `stale_permit` / `stale_manifest` / `false_complete` | 0 / 1 | violation latches |

Transitions:

- Environment: `start`, `commit_original`, `fail_original`, `finish_child`,
  `late_commit`, `revoke`, `change_manifest`.
- Controller: `wait`, `query`, `qualify`, `admit_retry_atomic` (A4) or
  `retry_check` + `retry_write` (not A4), `complete`, `pause`.

Assumptions:

- A1 `faithful query`: the query returns the true value of `store`; without it,
  the query may return any of empty/present/unknown.
- A2 `closure`: `closed=1` implies no further late commit; without it, `wait`
  may set `closed=1` while a child is still running, and `late_commit` may
  happen after closure.
- A3 `version binding`: `qualify` records the current manifest and admission
  requires `qual = manifest`; without it, `qualify` records m0 and admission
  only requires `qual = m0`.
- A4 `atomic admission`: the qualification check and the write are atomic;
  without it they split into `retry_check` and `retry_write`, and
  `revoke`/`change_manifest` may interleave.

Auxiliary invariant J: `obs=empty -> store=0`, `obs=present -> store=1`,
`obs!=none -> closed=1`, `phase=running -> obs=none`,
`closed=1 -> phase>=committed`, `qual!=none -> closed=1`, and under A2
`closed=1 -> child=0`.

## 2. Checks

Positive cases use an **inductive check**: Z3 checks whether
`J(s) and P(s) and Step(s,s') and not (J(s') and P(s'))` is satisfiable.
`unsat` means P is inductive under J, i.e. no state satisfying J can violate P
in one step; together with the initial-state check (initial state satisfies
J and P) this covers all reachable states.

| Theorem | Property P | Assumptions |
|---|---|---|
| T1 retry soundness | `dup=0` | A1+A2+A3+A4 |
| T2 admission atomicity | `stale_permit=0` | same |
| T4 requalification after change | `stale_manifest=0` | same |
| all properties | `dup=0 and stale_permit=0 and stale_manifest=0 and false_complete=0` | same |
| initial state | same as above | initial-state check |

T3 uses a two-world encoding: two worlds share the same "unknown" observation
but differ in `store`; the query asks whether some action is both safe and
complete in both. `unsat` means impossibility.

Ablations use shortest-counterexample search with depth <= 10: removing
A1/A2/A3/A4 should each produce `sat` and a concrete trace.

## 3. Preregistered acceptance

1. T1-T4, all_assumptions_safe and the initial-state check are all `unsat`.
2. All four ablations are `sat`, with traces landing on
   `admit_retry_atomic` and `retry_write` respectively.
3. Results are written to `formal/z3_report.json`, including every trace and
   `depth`; they can be re-run offline.
4. Claim only "machine-checked in this abstract model", not that the
   implementation is verified.

## 4. Limits

- Single operation, single retry; concurrency (R5), clocks (R3/R7), real
  process crashes (R11) and multiple hosts are not modeled.
- A1's "faithful query" is stronger than the paper's "complete and receipt
  bound"; the final version must split completeness and soundness.
- The state is a finite abstraction; the conclusion is an inductive invariant
  in this abstraction, not implementation-level verification.
