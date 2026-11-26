# R48 cross-layer closure result

2026-10-29. Protocol: `docs/R48_cross_layer_closure_protocol_20261029.md`
(section 8 contains the cancel-granularity amendment).

## 1. Rounds and verification

| Round | Runs | Result |
|---|---|---|
| `attempt1` | 320 | 8/13, exposed cancel recorded per `op` |
| `attempt2` | 320 | 13/13, zero SQLite mismatches |

`attempt2` covers 2 (replay) x 2 (cancel) x 2 (stop) x 2 (closure) x 2 faults x
10 seeds. Cancellation is recorded per `(op, attempt)`.

## 2. Result table

`eff` is the number of committed effects (identical across the 10 seeds of a
cell); `complete` is the number of task-level completions.

| replay | cancel | stop | closure | lost return eff/complete | late commit eff/complete |
|---|---|---|---|---|---|
| on | on | on | on | 1 / 10 | 1 / 10 |
| on | on | on | off | 2 / 0 | 1 / 10 |
| on | on | off | on | 1 / 10 | 1 / 10 |
| on | on | off | off | 2 / 0 | 2 / 0 |
| on | off | on | on | 1 / 10 | 1 / 10 |
| on | off | on | off | 2 / 0 | 2 / 0 |
| on | off | off | on | 1 / 10 | 1 / 10 |
| on | off | off | off | 2 / 0 | 2 / 0 |
| off | on | on | on | 1 / 10 | 0 / 0 |
| off | on | on | off | 1 / 0 | 0 / 0 |
| off | on | off | on | 1 / 10 | 1 / 10 |
| off | on | off | off | 1 / 0 | 1 / 0 |
| off | off | on | on | 1 / 10 | 1 / 10 |
| off | off | on | off | 1 / 0 | 1 / 0 |
| off | off | off | on | 1 / 10 | 1 / 10 |
| off | off | off | off | 1 / 0 | 1 / 0 |

## 3. Findings

**Attribution is exact.** Across all 320 runs, duplicates appear if and only if
"framework replay on, closure evidence off, and the effect is or will be
committed". Under lost return the duplicate remains even with cancel and stop on
(40/40), because the effect commits before the cancel arrives; under late commit
only cancel + remote stop together prevent the in-flight write (that cell: zero
duplicates, one effect, 10/10 complete). One formula covers all 320 cells with no
exception.

**Closure evidence is the only layer that works in both faults.** With closure
evidence on, duplicates are zero regardless of replay, cancel and stop; with
replay on, every cell completes 10/10 with exactly one effect (80/80). It covers
effects that are committed but unseen by the controller, not effects still in
flight.

**The cancel layer can only stop an uncommitted write.** Cancel on and stop off
does nothing under late commit (2 effects, 0 complete). Cancel + stop blocks the
in-flight late write before commit. Under lost return both are useless, which
shows that cancellation is not a post-commit remedy.

**Turning replay off removes duplicates but leaves the task incomplete.** With
replay off there are no duplicates, but with closure off every task pauses; only
closure on completes without replay.

**Each layer owns one segment.** Framework replay decides whether a second write
happens; cancel and stop decide whether the first write happens; closure evidence
decides whether the controller can know that the first write happened. Fixing one
layer covers only its segment: disabling replay sacrifices completion, cancel +
stop only handle late commits, and only closure evidence works in both faults,
at the price of the executor exposing the original call's and descendants'
terminal flags.

## 4. Optional LLM action subset

`runs/R48/llm1`: after a timeout with closure off and no cancel sent,
`deepseek-flash` at temperature 0.2 chose the action; the runner executed it.
20 runs (2 faults x 10 seeds). Verification: 4/4 checks, zero mismatches.

- Actions: `stop` 18, `cancel_wait` 2, `retry` 0.
- Effects: one per run; duplicates 0. The two `cancel_wait` runs were under lost
  return, where the effect had already committed before the cancel.
- With this prompt the model is conservative and avoids the retry failure mode,
  so the subset does not reproduce the duplicate that the deterministic table
  attributes to replay. The subset is prompt- and model-dependent external
  validity; the 320-cell table is unchanged.

## 5. Differences from pre-registration

None. The `attempt1` failure was a cancel-granularity defect, fixed in protocol
section 8 before the main run; the criteria were unchanged.

## 5. Paper integration

- Support P2 ("terminating, observable closure") with the cross-layer argument.
- Replace the descriptive narrative with the formula "duplicate iff replay on and
  closure off and the effect is committed".
- State the boundary of closure evidence: it covers committed-but-unobserved
  effects, not in-flight writes; the latter need cancel + remote stop.

## 6. Artifacts

- `runs/R48/attempt2/` (320 runs), `attempt1/` (failed round);
- `runs/R48/attempt2/verification.json`;
- `scripts/r48_service.py`, `run_r48.py`, `verify_r48.py`.
