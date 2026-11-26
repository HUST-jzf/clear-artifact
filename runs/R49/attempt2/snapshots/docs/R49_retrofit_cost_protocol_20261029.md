# R49 retrofit-cost protocol (pre-registered)

2026-10-29. Frozen before the first run. Question: why can a recovery
controller not simply fix the service, what is the minimum retrofit, and what
does each retrofit level cost?

R45 established *what* each capability combination can guarantee. R49 adds the
dimension R45 held fixed: who is allowed to change the service. The same
workload and the same two faults are run under three ownership regimes and four
retrofit levels.

## 1. Workload and faults

The five-step ticket workload of R45 (`create`, `reserve`, `attach`, `commit`,
`notify`), one fault per workflow, both faults injected at `attach`:

| Fault | Injection |
|---|---|
| `lost_return` | the effect commits, then the response is dropped |
| `late_commit` | the commit is delayed by 0.9 s; the controller times out at 0.3 s |

These are the two faults for which R45/C4 is safe and R45/C0, C3 are not; they
separate "minimum viable retrofit" from "no retrofit".

## 2. Retrofit levels

The levels are the R45 capability profiles, not new code paths:

| Level | Profile | Capabilities |
|---|---|---|
| L0 | C0 | business write only |
| L1 | C3 | + closure (lifecycle read) + faithful effect read |
| L2 | C4 | + version binding + atomic admission |
| L3 | C6 | + candidate staging with fence, finalize and abort |

The mapping L0-L3 is inherited from R45 so that every R49 cell can be compared
with the R45 frontier table without re-deriving it.

## 3. Ownership regimes

| Regime | Meaning | Effective profile per requested level |
|---|---|---|
| `self` | the developer owns the service | L0, L1, L2, L3 as requested |
| `read_only` | a third party allows read-only endpoints to be added, no write-path change | L0, L1, L1, L1 |
| `unmodifiable` | the service cannot be changed at all | L0, L0, L0, L0 |

`read_only` adds closure and effect reads but cannot add an admission
transaction, so L2 and L3 collapse to L1. `unmodifiable` collapses everything to
L0. The collapse is the treatment; it is not a failed cell.

## 4. Controllers

One controller per effective profile, the strongest policy that profile can
support (from R45, unchanged):

| Effective profile | Controller |
|---|---|
| C0 | `clear_pause` |
| C3 | `clear_evidence` |
| C4 | `clear_evidence` |
| C6 | `clear_fenced` |

Using `clear_evidence` at both L1 and L2 keeps the controller fixed across the
step that changes the guarantee; only the service capability changes.

## 5. Matrix

3 ownership x 4 levels x 2 faults x 10 seeds = 240 workflows. One service
process per effective profile (C0, C3, C4, C6); workflow ids encode ownership
and requested level.

## 6. Metrics

Per workflow, recomputed from the workflow SQLite file: committed effects,
duplicates, stale effects, provisional rows, rejections, terminal state,
requests, wall-clock and logical database size.

## 7. Cost accounting (mechanical)

Cost is measured on the two sides separately.

Service side, from the axes reported by `GET /manifest` at run time:

| Capability | Endpoints |
|---|---|
| base | `POST /w/{wf}/{step}`, `GET /permit/{wf}`, `GET /manifest`, `GET /w/{wf}/manifest`, `GET /w/{wf}/state` |
| closure | `GET /w/{wf}/ops/{op}` |
| read | `GET /w/{wf}/ops/{op}/effects` |
| admission | `POST /w/{wf}/admit` |
| staging | `POST /w/{wf}/fence`, `POST /w/{wf}/finalize`, `POST /w/{wf}/abort` |

Endpoint counts are therefore 5 (C0), 7 (C3), 8 (C4) and 11 (C6). New endpoints
relative to L0 are 0, +2 (both read-only), +3 (one of them write-path) and +6
(two write-path groups).

Service handler lines are counted with `ast`: non-blank, non-comment lines of
`Store.lifecycle` and `Store.effects` for L1, `Store.admit` for L2,
`Store.allocate`, `Store.finalize` and `Store.abort` for L3. Controller lines
are counted the same way for the policy function body.

The client-side retrofit is unchanged across levels: per R27 the guard is 25
lines, exposes 2 configuration items (`budget`, `after_initial`) and requires 0
lines of business-code change. R26 established that admission plus receipt (L2)
is the minimum viable retrofit for the loss faults; R49 tests that claim under
the ownership constraint and adds the cost curve.

## 8. Hypotheses and acceptance

H1. Under `self`, L2 is the minimum level that is safe and complete under both
faults; L0 pauses, L1 duplicates under `late_commit`.

H2. Under `read_only`, no level is safe and complete under both faults: L2 and
L3 are L1 in effect and duplicate 10/10 under `late_commit`.

H3. Under `unmodifiable`, every level pauses in both faults (100% pause, 0
completed), and no workflow writes a duplicate or a stale effect.

H4. Cost is monotone in the effective level: median requests satisfy
L0 < L1, L0 < L2 and L2 < L3, while L1 and L2 differ by at most one request;
service endpoints and cumulative service handler lines increase with the level;
controller cost and configuration items are constant.

Acceptance is the conjunction of H1-H4 plus: zero SQLite recompute mismatches,
and one homogeneous outcome class per cell across seeds.

## 9. Procedure and rounds

1. `smoke1`: 1 seed, all 24 cells, to calibrate the expectations; kept.
2. `attempt1`: 10 seeds, 240 workflows, main round.
3. `verify_r49.py --run runs/R49/attempt1` recomputes every metric from SQLite
   and checks H1-H4.

Frozen files: this protocol, `scripts/r45_service.py`, `scripts/r45_client.py`,
`scripts/run_r49.py`, `scripts/verify_r49.py`, SHA-256 in `freeze.json`.

## 10. Boundaries

- The ownership regimes are modelled by capability collapse, not by a real
  third-party API. The claim is about which capabilities can be obtained, not
  about procurement time or organisational approval.
- Line counts are mechanical; they do not measure review effort or migration
  risk.
- Only two faults are run. L3 has no advantage over L2 on these two faults; its
  advantage under `lost_before_commit` is R45's result, not re-measured here.

## 11. Registered expectations (before the run, not results)

| Ownership | L0 | L1 | L2 | L3 |
|---|---|---|---|---|
| `self` | pause / pause | complete / unsafe | complete / complete | complete / complete |
| `read_only` | pause / pause | complete / unsafe | complete / unsafe | complete / unsafe |
| `unmodifiable` | pause / pause | pause / pause | pause / pause | pause / pause |

Cells are `lost_return` / `late_commit`. "complete" is safe completion with
exactly one effect per step; "unsafe" means at least one duplicate or stale
effect; "pause" is a safe pause.

## 12. Amendment after `runs/R49/attempt1` (before the main round)

`attempt1` ran all 240 workflows with 0 process failures, but two workflows in
the `self`/L2/`late_commit` cell ended in a safe pause at `commit` with the
reason `permit_revoked`. Both had 10 requests instead of the usual 20, no effect
for `commit`, and no rejection row: the pause came from a failed `GET /permit`
exchange, not from a service decision. A one-seed probe reproduced the same
workflow completing both faults.

The probe also exposed that `POST /control/stop` can be lost when its response
socket is already closed, which leaves the service process alive. Neither
observation is a capability result.

Amendment, applying to the runner and verifier only:

1. `run_r49.py` records every exchange with no status or a 5xx status per
   workflow (`transport_errors`) and no longer treats a missing status as a
   pause without recording it.
2. The runner waits for `private/stats.json` after the stop request and
   terminates the service if it is still alive; a missing stats file is an
   error, not a silent empty result.
3. `verify_r49.py` fails if any workflow recorded a transport error outside the
   injected faulty step (`attach`), so an incidental exchange failure cannot be
   reported as a safe pause. Failures on `attach` are the fault itself.

`attempt1` is kept as a failed round. `attempt2` is the main round. No
hypothesis, cell, expected class or cost criterion changes.
