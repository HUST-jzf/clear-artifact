# R47 task-level intent protocol (pre-registered)

2026-10-29. Frozen before the run. Question: after the user changes intent in
the middle of a task, can single-binding safety compose into task-level safety,
and how should effects left by the old intent be disposed of?

## 1. Scenarios

Task: assign a seat on one ticket. Old intent A is `seat:12A`; new intent B is
`seat:14C`.

| Case | Order |
|---|---|
| `change_before_commit` | A's `attach` gets a lost return (the effect is committed, the controller does not see it); the user changes to B before A is confirmed |
| `change_after_commit` | A is confirmed committed, then the user changes to B |
| `late_after_b` | B is committed, then A's late write lands |

## 2. Disposals

| Disposal | Behaviour |
|---|---|
| `none` | each binding runs CLEAR on its own; old effects are not touched |
| `compensate_after_commit` | after B commits, write one compensating effect for every active old effect (two writes) |
| `ownership_transfer` | B's write and the transfer of old-effect ownership happen in one transaction (one write) |
| `pause_escalate` | if an old binding has an active effect, pause and escalate; do not write B |

## 3. Matrix

3 cases x 4 disposals x 6 runs = 72 deterministic runs. Runs 1-3 of each cell
perform the disposal on a clean network; runs 4-6 inject `lost_before_commit` on
the disposal request itself, exposing the new failure window that a disposal
adds. `none` and `pause_escalate` perform no disposal, so their two subgroups
behave the same.

No real LLM is used. The LLM subset is not run in this campaign and the reason is
recorded in the result document.

## 4. Metrics

- `residual`: active old-intent effects;
- `duplicates`: active new-intent effects minus one;
- `task_complete`: exactly one B effect and `residual=0`;
- `escalated`: paused and escalated;
- `writes`: all write operations of the task;
- `visible_inconsistency`: `residual>0` or `duplicates>0`.

## 5. Acceptance

1. `none` has `residual=1` and `task_complete=false` in all three cases: A's
   effect is committed, whether or not the controller knows about it.
2. `compensate_after_commit` reduces `residual` to 0 in the normal subgroup of
   `change_before_commit` and `change_after_commit`, with 3 writes; it stays at
   1 under `late_after_b` because the late write has not landed when the
   compensation runs; the disposal-fault subgroup is 1 in all cases.
3. `ownership_transfer` reduces `residual` to 0 in the normal subgroup of all
   three cases, with 2 writes (the same as `none`: the transfer and the new
   intent's write are one atomic operation); the disposal-fault subgroup is 1 in
   all cases.
4. `pause_escalate` escalates in 100% of the two cells where the old effect is
   visible and does not write B, `task_complete=false`; under `late_after_b` it
   cannot see the in-flight write, does not escalate, and `residual=1`.
5. No disposal clears `residual` when the disposal request itself fails.
   Compensation can only dispose of visible effects; transfer rejects in-flight
   writes through the old binding's epoch.
6. Property: task-level safety = single-binding safety + intent epoch + disposal
   of old effects. Compensation covers only committed visible effects; pausing
   covers only visible old effects; only "new intent + old-binding epoch + old
   effect disposal" in one atomic operation covers all three cases.

Revision before the run: the original clause 5 said "without extra writes",
which does not match the write counter, because transfer merges the new write
with the disposal and writes as many times as `none`. The clause was rewritten
in countable terms; the direction of the criterion is unchanged. This revision
was written before any R47 data existed.

## 6. Artifacts

`scripts/r47_service.py`, `r47_client.py`, `run_r47.py`, `verify_r47.py`;
`runs/R47/attempt1`; a result document.

## 7. Optional LLM disposal subset (registered before running)

Purpose: check whether a real model chooses a disposal that is safe for each
case. The runner executes the chosen disposal deterministically, so the effect
counts stay attributable.

- Model: `deepseek-flash`, temperature 0.2, max 120 tokens.
- Prompt: one paragraph describing the case; four disposal names with their
  behaviour; output `{"disposal": "..."}`.
- 6 runs per case (18 total). Metrics: residual, task completion, writes,
  escalation, and the distribution of choices.
- A choice that clears the residual in `late_after_b` is possible only with
  `ownership_transfer`; compensation and pause are expected to fail there.

## 8. Expectations (registered before the run, not results)

`none` keeps the residual everywhere; compensation and transfer clear it but add
writes, transfer with fewer writes; both show the residual again when the
disposal fails; pause-escalation drives completion to zero without silently
leaving the old effect. The highest task-level completion is expected from
`ownership_transfer` in the normal subgroup.
