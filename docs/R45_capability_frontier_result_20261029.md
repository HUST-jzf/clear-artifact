# R45 capability-frontier result

2026-10-29. Protocol: `docs/R45_capability_frontier_protocol_20261029.md`
(sections 11 and 12 contain the pre-run amendment and the post-smoke calibration).

## 1. Rounds and verification

| Round | Seeds | Workflows | Purpose | Verification |
|---|---|---|---|---|
| `smoke0` | 1 | 8 (C0 only) | service and fault calibration | not verified separately |
| `smoke1` | 1 | 88 (all profiles) | expectation calibration | 273/273 |
| `attempt1` | 10 | 880 | exploration | 273/273 |
| `attempt2` | 20 | 1,760 | main | 273/273, zero SQLite mismatches |

`attempt2` has no failures. `verify_r45.py` re-reads committed effects, stale
effects, provisional rows, duplicates and rejections from each workflow's
SQLite file, compares them with `completion.json` (0 mismatches), and then
checks 273 criteria over 22 (profile, policy) x 4 faults x 20 seeds.

## 2. Frontier table

C = safe completion, P = safe pause (no duplicate, no stale write, no false
completion), X = unsafe. Requests are the median over the 80 workflows of the
cell; milliseconds are the cell median.

| Profile/policy | lost return | late commit | lost before commit | revoke | Requests | Time |
|---|---|---|---|---|---|---|
| C0 / `clear_pause` | P | P | P | X | 9 | 81 ms |
| C0 / `timeout_retry` | X | X | C | X | 16 | 130 ms |
| C1 / `clear_closure` | C | X | P | X | 13 | 135 ms |
| C1 / `timeout_retry` | X | X | C | X | 16 | 157 ms |
| C2 / `verify_retry` | C | X | C | X | 16 | 186 ms |
| C2 / `timeout_retry` | X | X | C | X | 16 | 178 ms |
| C2s / `verify_retry` | X | X | C | X | 17 | 193 ms |
| C2s / `timeout_retry` | X | X | C | X | 16 | 149 ms |
| C3 / `clear_evidence` | C | X | P | X | 15 | 169 ms |
| C3 / `verify_retry` | C | X | C | X | 16 | 168 ms |
| C3s / `clear_evidence` | C | X | P | X | 15 | 167 ms |
| C3s / `verify_retry` | X | X | C | X | 17 | 192 ms |
| C4 / `clear_evidence` | C | C | P | P | 15 | 150 ms |
| C4 / `verify_retry` | C | X | C | P | 16 | 160 ms |
| C4 / `timeout_retry` | X | X | C | P | 16 | 145 ms |
| C5 / `clear_fenced` | P | C | C | P | 20 | 210 ms |
| C5 / `timeout_retry` | X | X | C | P | 16 | 164 ms |
| C6 / `clear_evidence` | C | C | P | P | 19 | 239 ms |
| C6 / `clear_fenced` | C | C | C | P | 24 | 270 ms |
| C6 / `timeout_retry` | X | X | C | P | 16 | 210 ms |
| C7 / `dedup_versioned` | C | C | C | P | 16 | 193 ms |
| C7 / `timeout_retry` | X | X | C | P | 16 | 197 ms |

Only five pairs are safe in all four faults: `C4/clear_evidence`,
`C5/clear_fenced`, `C6/clear_evidence`, `C6/clear_fenced`,
`C7/dedup_versioned`. Every one of them pauses under `revoke`, because the
correct action after revocation is not to write.

## 3. Findings

**Tier-0 has no policy that is both safe and complete.** CLEAR in C0 pauses in
all four faults (80/80 x 4) but leaves one stale effect under `revoke`: the
service accepted the request before the permit was revoked, and the pause comes
after the effect. Blind retry is safe only under `lost_before_commit`, because
there is no effect to duplicate; a controller without evidence cannot tell that
cell apart from a lost return, so CLEAR still has to pause.

**A single capability is not enough.** C1 (closure only) duplicates 20/20 under
`late_commit` and leaves a stale write under `revoke`. C2 (read only) duplicates
under `late_commit` and reports completion over a stale effect under `revoke`.
C3 (closure + read) still has both cells. C2s/C3s show that "having a read" and
"having a trustworthy read" are different: a stale index turns C2's safe
`lost_return` cell unsafe, while C3 recovers it through closure evidence.

**Tier-1 is enough, provided the policy actually uses admission.**
`C4/clear_evidence` goes through atomic admission and is safe in all four cells:
safe completion under lost return and late commit, safe pause under lost before
commit and revocation. `verify_retry` on the same profile uses plain writes and
still duplicates 20/20 under late commit; blind retry duplicates in both loss
cells. Capability present is not capability used.

**C4's late-commit safety comes from the second admission check.** The delayed
request enters the admission transaction after the delay, when the retry has
already written the receipt; admission returns the existing receipt instead of
inserting a second effect. This was found by `smoke1` and recorded in protocol
section 12 before the main run.

**Tier-2 needs no read surface at all.** C5 is staging + fence only and is safe
in all four cells: a lost return is detected through the fence and the policy
pauses when it cannot confirm (one effect plus one provisional row); a late
commit is rejected by the stale fence; a lost-before-commit is settled under a
new fence; revocation is rejected by the atomic qualification check. The cost is
20 requests (Tier-0 pause 9, Tier-1 15) and one unconfirmable pause.

**C6 and C7 cover the most.** `C6/clear_fenced` completes in three cells and
pauses under revocation; `C7/dedup_versioned` does the same with a stable key.
The difference between them is not in this experiment: key stability depends on
the identity regime, which is R46.

**Cost.** Every workflow's logical SQLite size is 36 KB in this workload, so
evidence storage does not discriminate; the difference is in requests and time.
Pausing is cheapest (9 requests), fence settlement is the most expensive
(`C6/clear_fenced`, 24 requests, 270 ms), and admission sits in between
(15-19).

## 4. Differences from pre-registration

Two, both written into protocol section 12 before the main run: C4 admission
suppresses late commits, and C6 fence settlement completes under lost-before-
commit. Both increase coverage; neither relaxes a criterion.

## 5. Paper integration

- Add the frontier table of section 2.
- Carry the argument with four sentences: Tier-0 can only pause; one capability
  is not enough; Tier-1 needs admission to be used; Tier-2 needs no read.
- Do not list fencing, admission or dedup as contributions; they are capability
  conditions.
- Use the revoke cell ("pause with one stale effect") as evidence that a
  controller cannot undo an effect the service already accepted.

## 6. Artifacts

- `runs/R45/attempt2/` (main, 1,760 workflows), `attempt1/` (exploration),
  `smoke0/`, `smoke1/` (calibration);
- `runs/R45/attempt2/verification.json` (273 criteria, frontier, cost medians);
- `scripts/r45_service.py`, `r45_client.py`, `run_r45.py`, `verify_r45.py`.
