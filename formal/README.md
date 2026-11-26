# CLEAR formal models (R6 pilot and R17 Z3 unbounded checks)

2026-10-21. This directory contains two models:

- `z3_model.py` / `z3_protocol.md` / `z3_report.json`: the **R17 unbounded
  inductive check** (Z3 5.3.1). T1-T4 are inductive invariants under A1-A4
  (`unsat`); removing A1-A4 one at a time yields shortest counterexamples of
  6-8 steps (`sat`). `scripts/verify_r17.py` reports 21/21. The paper should
  cite this model and claim only "machine-checked in this abstract model".
- `model.py` / `report.json`: the **R6 bounded explicit-state pilot** described
  below. It is kept for history and comparison and is no longer the final
  formal evidence.

```powershell
python formal/z3_model.py          # writes formal/z3_report.json
python scripts/verify_r17.py       # writes formal/z3_verification.json (21 checks)
```

---

The remainder of this file describes the R6 **bounded abstract model**, which
checks whether the CLEAR recovery guard can violate three properties under four
assumptions and whether removing any assumption produces a concrete
counterexample. It is not a formal verification of the implementation and not a
substitute for a TLA+ specification.

## Model

State: whether the root/child executor has terminated, whether registration is
complete, whether a late commit exists, whether an effect exists and its origin
(original/retry), the last query, whether closure was observed, the qualified
manifest version, the current manifest, the permit, whether a retry is armed,
whether a retry happened, and three violation flags.

Actions:

- Environment: `commit_original`, `fail_original`, `finish_child`,
  `late_commit`, `revoke_permit`, `change_manifest`.
- Controller: `wait` (affected by A2), `query` (A1), `qualify` (A3), `retry`
  (A4), `complete`, `pause`.

Guard: observed closure, then an empty query, then the current manifest is
qualified, then the permit is valid; only then may it retry, and it may retry
once. The query must follow closure; an effect invalidates older queries.

## Properties

- S1: no duplicate effect (retry while the original exists, or a late original
  commit after retry).
- S2: no write while the permit is revoked or the manifest is not qualified.
- S3: no completion without a real effect.

## Assumptions

- A1: the effect query faithfully reflects the binding (complete, no forgery).
- A2: the host registers every descendant that can produce effects and exposes
  true termination.
- A3: manifest changes are observable and old qualifications cannot be reused
  across versions.
- A4: the qualification check and the write are atomic, or the write
  re-validates the permit.

## Run

```powershell
python formal/model.py --output formal/report.json
```

The model explores to depth 14 and outputs the shortest counterexample trace for
each assumption combination and scenario. Current results:

- A1-A4 all hold: no violation.
- Remove A1: in `plain` and `registered_pending`,
  `commit_original -> wait -> query_empty -> retry` duplicates.
- Remove A2: in the two pending scenarios (`registered_pending`,
  `unregistered_pending`), `fail_original -> wait -> query -> retry ->
  late_commit_duplicate` duplicates; `plain` has no pending child, so no
  counterexample appears.
- Remove A3: in `plain` and `registered_pending`,
  `fail_original -> change_manifest -> wait -> query -> retry` writes under a
  stale manifest; `unregistered_pending` has no counterexample.
- Remove A4: in `plain` and `registered_pending`,
  `retry_check -> revoke_permit -> retry_write` writes under a stale permit;
  `unregistered_pending` has no counterexample.

Thus "removing any assumption is unsafe" should be read as "**some scenario**
becomes unsafe", not that every scenario violates the property;
`formal/report.json`'s `counterexample_for_each_removed_assumption` is also
aggregated over "at least one scenario".

This is consistent with the empirical counterexamples in U04/U05/H05/H06, but
the model is abstract and does not replace implementation-level verification.

## Limits

- The state space and depth are bounded; only a single operation, a single
  retry and three scenarios are covered.
- A1 is modeled as a "faithful query", stronger than the paper's "complete but
  possibly unsound" assumption; the paper's T1 needs completeness plus receipt
  binding, and the formal version must split them.
- Concurrency, clocks, real process crashes and remote services are not
  modeled; those are covered by R2/R5.
- There is no mechanized TLA+; if the paper needs one, the final version should
  add a TLA+ specification and a TLC run.
- This model is a pilot and must not be cited as the final R6 result; the final
  version must freeze a protocol first.
