# R48 cross-layer closure protocol (pre-registered)

2026-10-29. Frozen before the first run. Question: which layer breaks
"terminating, observable closure", and what evidence is needed?

## 1. Layers

| Layer | Behaviour | Switch |
|---|---|---|
| framework replay | re-issue the same step after a timeout (new attempt handle) | `replay` on/off |
| cancel propagation | send the cancel to the executor when the controller gives up | `cancel` on/off |
| remote stop | the executor drops a request whose attempt was cancelled before the write | `stop` on/off |
| closure evidence | the executor exposes the terminal flag and receipt of the original call | `closure` on/off |

## 2. Scenario

One `attach` step with two faults: `lost_return` (commit, then lose the response)
and `late_commit` (delay the commit by 0.9 s; the controller times out at 0.3 s).

Controller flow: issue `attach`; on timeout or error, if `cancel` is on, send a
cancel; if `closure` is on, poll the original call's terminal flag (limit 2 s)
and complete on a receipt; if still incomplete and `replay` is on, re-issue the
step; otherwise pause.

## 3. Matrix

2 (replay) x 2 (cancel) x 2 (stop) x 2 (closure) x 2 faults x 10 seeds = 320
runs. One service process per (closure, stop) pair; each (replay, cancel, fault,
seed) has its own workflow.

## 4. Metrics

`effects` (committed effects), `duplicates` (effects minus one), `completed`
(controller complete with exactly one effect), `paused`, and layer attribution
(which switch combination produces duplicates).

## 5. Acceptance

1. `closure` on: zero duplicates in both faults and all combinations, and
   exactly one effect when completed.
2. `closure` off, `replay` on, `cancel` off: duplicates 10/10 in both faults.
3. `late_commit` + `replay` on + `closure` off: zero duplicates when both
   `cancel` and `stop` are on; duplicates 10/10 with `cancel` on and `stop` off.
4. `lost_return` + `replay` on + `closure` off: duplicates 10/10 even with
   `cancel` and `stop` on, because the effect was committed before the cancel.
5. `replay` off: no duplicates; with `closure` off the task does not complete.
6. No single switch removes duplicates and completes the task in both faults
   across all combinations.

## 6. Artifacts

`scripts/r48_service.py`, `run_r48.py`, `verify_r48.py`; `runs/R48/attempt1`;
a result document.

## 7. Expectations (registered before the run, not results)

Duplicates appear only when `replay` is on, `closure` is off, and the effect has
been or will be committed. Cancellation is too late under `lost_return`; under
`late_commit`, cancel plus stop prevents the effect. Closure evidence is the only
layer that works in both faults.

## 8. Amendment (after `runs/R48/attempt1`, before the main run)

`attempt1` exposed the granularity of cancellation: it was recorded per `op`, so
"cancel then replay" also blocked the replay, and the `lost_return` + cancel +
stop cell had 1 effect instead of 2.

Amendment: cancellation is recorded per `(op, attempt)` and revokes only the
in-flight attempt at the time of the cancel; a replay uses a new attempt handle
and is not blocked by an old cancel. This changes only the scope of the cancel,
not the four switches or the criteria. `attempt1` is kept as a failed round.
