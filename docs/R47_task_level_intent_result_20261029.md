# R47 task-level intent result

2026-10-29. Protocol: `docs/R47_task_level_intent_protocol_20261029.md`.

## 1. Rounds and verification

`runs/R47/attempt1`: 3 cases x 4 disposals x 6 runs = 72 deterministic runs, no
failures. `verify_r47.py` reports 59/59 and re-reads effects, states and write
counts from each workflow's SQLite file with zero mismatches.

Runs 1-3 of each cell perform the disposal on a clean network; runs 4-6 inject
`lost_before_commit` on the disposal request.

## 2. Result table

`residual` is the number of active old-intent effects; `complete` is task-level
completions out of 6; `escalated` is the number of escalations; `writes` is the
server-side write count.

| Disposal | A not committed, change to B | A committed, change to B | A late, after B |
|---|---|---|---|
| `none` | residual 1, complete 0/6, 2 writes | residual 1, complete 0/6, 2 writes | residual 1, complete 0/6, 2 writes |
| `compensate_after_commit` | residual 0/1, complete 3/6, 2-3 writes | residual 0/1, complete 3/6, 2-3 writes | residual 1, complete 0/6, 2-3 writes |
| `ownership_transfer` | residual 0/1, complete 3/6, 1-2 writes | residual 0/1, complete 3/6, 1-2 writes | residual 0/1, complete 3/6, 1 write |
| `pause_escalate` | residual 1, complete 0/6, escalate 6/6, 1 write | residual 1, complete 0/6, escalate 6/6, 1 write | residual 1, complete 0/6, escalate 0/6, 2 writes |

Normal-subgroup task-level completions: `ownership_transfer` 9/9,
`compensate_after_commit` 6/9, `none` 0/9, `pause_escalate` 0/9.

## 3. Findings

**Single-binding safety does not compose.** `none` leaves one old-intent effect
in all three cases, even though each binding runs CLEAR safely. An old effect
does not disappear when a new intent commits.

**Compensation disposes only of what it can see.** It clears the residual in the
first two cases but not in `late_after_b`: when the compensation runs, the old
write is still in flight and there is nothing to compensate. It also raises the
write count from 2 to 3, and the residual returns when the disposal request
itself is lost.

**Ownership transfer needs the old binding's epoch.** It puts the new intent's
write and the old-effect disposal in one transaction and increments the old
binding's epoch. In `late_after_b` the late old write carries the old epoch and
is rejected, so the residual is 0 in all three normal cells, with the same write
count as `none` (2; only 1 in the late cell because the old write is rejected).
Its cost is a per-binding epoch in the service, not a generic compensation
endpoint.

**Pause-escalation covers only visible old effects.** It escalates in 100% of
the two cells where the old effect is visible and does not write B. Under
`late_after_b` it cannot see the in-flight write, writes B, and the old write
lands afterwards, leaving residual 1. It hands the decision to a human but does
not undo what has already happened or is about to happen.

**Task-level property.** Task-level safety = single-binding safety + intent
epoch + disposal of old effects. Single-binding safety prevents duplicates and
stale writes; the intent epoch lets a new intent reject in-flight old writes,
which compensation cannot do; disposal marks or transfers old committed effects,
which pausing cannot do. Missing any one leaves `residual` or `duplicates`
non-zero in at least one of the three cases.

## 4. Optional LLM disposal subset

`runs/R47/llm1`: `deepseek-flash` at temperature 0.2 chose one of the four
disposals for each case, 6 runs per case (18 total). The runner executed the
chosen disposal deterministically. Verification: 4/4 checks, zero mismatches.

- The model chose `none` in 18/18 runs, so task completion was 0/18 and the old
  effect stayed active (residual 1) in every case.
- No duplicates, and no completion with a non-zero residual.
- The neutral prompt does not make the model consider old-effect disposal. The
  safe behaviour in the deterministic table comes from an explicit disposal
  protocol, not from the model's free choice. A prompt that states the residual
  objective would be a separate variant and is not part of this subset.

## 5. Differences from pre-registration

None. The write-count clause was rewritten before the run and matches the
measured counts (transfer 2, `none` 2, compensation 3).

## 5. Paper integration

- Add the task-level property as a natural extension of the third contribution.
- Use this table to show that fencing/admission/dedup solve one binding, while
  task level also needs an epoch and disposal.
- The compensation failure and the pause failure under `late_after_b` are the
  evidence that in-flight writes are invisible; connect them to R46's intent
  ambiguity.

## 6. Artifacts

- `runs/R47/attempt1/` (72 runs), `verification.json`;
- `scripts/r47_service.py`, `r47_client.py`, `run_r47.py`, `verify_r47.py`.
