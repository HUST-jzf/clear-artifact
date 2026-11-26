# R45 capability-frontier protocol (pre-registered)

2026-10-29. Frozen before the first run. The experiment produces a frontier of
"service capability profile x achievable recovery guarantee" and answers two
questions: what is the strongest guarantee under each combination of evidence
and commit capabilities, and is the Tier-0 pause the optimal action.

## 1. Scope

- Workload: five-step ticket workflow `create -> reserve -> attach -> commit -> notify`; the fault is injected at `attach`.
- Faults: `lost_return`, `late_commit`, `lost_before_commit`, `revoke`.
- Unit of observation: one workflow; each workflow runs in its own directory with its own SQLite file.
- No real LLM is used; controllers are deterministic so that differences are attributable to the capability profile.

## 2. Capability profiles

Six axes:

| Axis | Values | Meaning |
|---|---|---|
| `closure` | 0/1 | original call and descendants expose a terminal flag and a bound receipt |
| `read` | 0/1/`stale` | authoritative effect index; `stale` means the index lags |
| `version` | 0/1 | evidence and writes are bound to the current manifest version |
| `admission` | 0/1 | atomic "no effect + write" endpoint |
| `staging` | 0/1 | candidate effect can be staged and settled by a fence |
| `dedup` | 0/1 | stable idempotency key + atomic dedup |

| Profile | closure | read | version | admission | staging | dedup | Tier |
|---|---|---|---|---|---|---|---|
| C0 | 0 | 0 | 0 | 0 | 0 | 0 | Tier-0 plain write |
| C1 | 1 | 0 | 0 | 0 | 0 | 0 | closure only |
| C2 | 0 | 1 | 0 | 0 | 0 | 0 | read only |
| C3 | 1 | 1 | 0 | 0 | 0 | 0 | closure + read |
| C4 | 1 | 1 | 1 | 1 | 0 | 0 | Tier-1 |
| C5 | 0 | 0 | 0 | 0 | 1 | 0 | Tier-2 |
| C6 | 1 | 1 | 1 | 1 | 1 | 0 | Tier-1 + settlement |
| C7 | 0 | 0 | 0 | 0 | 0 | 1 | stable key + atomic dedup |

`C2s` and `C3s` are the `stale`-read variants of C2 and C3.

## 3. Policies

Each profile runs only the policies it can deploy:

- C0: `clear_pause`, `timeout_retry`.
- C1: `clear_closure`, `timeout_retry`.
- C2/C2s: `verify_retry`, `timeout_retry`.
- C3/C3s: `clear_evidence`, `verify_retry`.
- C4: `clear_evidence`, `verify_retry`, `timeout_retry`.
- C5: `clear_fenced`, `timeout_retry`.
- C6: `clear_evidence`, `clear_fenced`, `timeout_retry`.
- C7: `dedup_versioned`, `timeout_retry`.

`timeout_retry` is the naive baseline: retry on timeout without reading any evidence.

## 4. Matrix

4 faults x 20 seeds x 10 profiles x 2-3 policies, about 1,700-1,900 workflows.
Each (profile, policy, fault, seed) has its own workflow ID and SQLite file.
Failed and calibration rounds are kept under `runs/R45/attemptN`.

## 5. Metrics

- `safe_complete`: completed with no duplicate, no stale write and no false completion;
- `duplicates`: committed effects for one binding minus one;
- `stale_writes`: writes after revocation or version invalidation;
- `false_complete`: reports completion without a valid receipt;
- `paused`: stops for lack of evidence or capability;
- `requests`, `storage_bytes`.

## 6. Acceptance

1. C4 and C7 reach safe completion under their safe policy; `timeout_retry` duplicates under `late_commit`.
2. C5 is safe-complete or safe-pause under `lost_return`/`late_commit`, with no duplicates and no stale writes.
3. No C0 policy is both safe and complete; the CLEAR pause rate is 100%.
4. C1/C2/C3 show that a single capability is not enough.
5. A frontier table: each profile x policy as safe-complete / safe-pause / unsafe, plus request and storage cost.

If C0 yields a policy that is both safe and complete, the capability definition is incomplete and the protocol must be fixed before rerunning.

## 7. Artifacts

`scripts/r45_service.py`, `r45_client.py`, `run_r45.py`, `verify_r45.py`;
`runs/R45/attempt1`; this protocol; a result document.

## 8. Reuse and additions

Reuse: R18 (split read surfaces), R26 (retrofit ladder), R30 (evidence outage),
R38 (fence settlement), R44 (equal capability), R36 (frontier vs fence).
Additions: unified six capability flags, the `stale` read variant, the
profile x policy frontier aggregation, and the C0 "no safe completion" check.

## 9. Stop conditions

- Any unexplained duplicate or stale write stops the round and keeps it as a failed round;
- process exit, port conflict or SQLite lock timeout is an infrastructure failure; keep the log and rerun a new attempt;
- two rounds with the same anomaly in the same profile: fix the protocol or the service before adding seeds.

## 10. Expectations (registered before the run, not results)

C4 and C7 safe-complete; C5 safe-complete or safe-pause; C1/C2/C3 each have at
least one unsafe cell; C0 pauses everywhere. The frontier is expected to show
safe completion covered by C4/C5/C7, partial coverage by C3, and only pause for
C0-C2.

## 11. Amendment before the first run (2026-10-29, no R45 data yet)

Written before any data was produced; the criteria were not changed afterwards.

### 11.1 Process model

"An independent service process per (profile, policy, fault, seed)" is replaced
by "one service process per profile; each (policy, fault, seed) has its own
workflow ID and SQLite file". The profile is fixed for the lifetime of the
process; per-workflow restarts add startup noise and port churn without changing
the observable semantics. Workflows share no table or state.

### 11.2 Fault and revoke semantics

All faults are injected at `attach`:

| Fault | Service behaviour |
|---|---|
| `lost_return` | commit the effect, then close the connection |
| `late_commit` | delay the commit by 0.9 s; the controller times out at 0.3 s |
| `lost_before_commit` | set `terminal=1, receipt=NULL`, close, write no effect |
| `revoke` | revoke the permit (`allowed=false`, `epoch+1`) and publish a new manifest version before the write |

A plain write records the revoked request as an `allowed=0` stale effect and
returns `committed`. A write that performs the qualification check in the same
transaction (admission, staging, dedup) rejects it with `403
stale_qualification` and writes no effect.

### 11.3 Exact definitions

`safe`: no duplicate, no stale write, no false completion. Three states:
`safe_complete` (completed and safe), `safe_pause` (paused and safe), `unsafe`
(everything else). `false_complete`: reports completion but has a duplicate, a
stale effect or a missing step. Duplicates and stale writes count only
`status=committed` effects; `provisional` rows are reported separately. The C0
criterion becomes: `clear_pause` pauses in all four faults; `timeout_retry` is
safe and complete only under `lost_before_commit`, and duplicates or writes
stale effects in the other three.

### 11.4 Expected frontier after the amendment

C4 is expected to fail `late_commit`; C6 is expected to cover it. All other
rows are unchanged: only policies with atomic qualification (C4/C5/C6/C7) avoid
the stale residual under `revoke`.

## 12. Calibration after smoke runs (`smoke0`, `smoke1`, before the main run)

`smoke0` (C0, 1 seed) and `smoke1` (all profiles, 1 seed, 273/273 checks)
exposed two behaviours that differ from section 11.4. Both come from capability
semantics, not from an implementation defect, so the expectations were corrected
without changing the service:

1. **C4 admission also suppresses late commits.** The delayed request enters the
   admission transaction only after the delay; by then the retry has written the
   receipt, so admission returns the existing receipt instead of inserting a
   second effect. `C4/clear_evidence` is therefore safe-complete under
   `late_commit`. The same profile's `verify_retry` uses the plain write path and
   still duplicates.
2. **C6 fence settlement completes under `lost_before_commit`** instead of
   pausing: it does not read the lifecycle and settles a provisional effect.

The set of (profile, policy) pairs that are safe in all four faults is therefore:
`C4/clear_evidence`, `C5/clear_fenced`, `C6/clear_evidence`,
`C6/clear_fenced`, `C7/dedup_versioned`. `smoke0` and `smoke1` are kept as
calibration rounds and are not part of the result table.
