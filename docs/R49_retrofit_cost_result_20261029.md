# R49 retrofit-cost result

2026-10-29. Protocol: `docs/R49_retrofit_cost_protocol_20261029.md`
(section 12 contains the post-`attempt1` amendment).

## 1. Rounds and verification

| Round | Seeds | Workflows | Purpose | Verification |
|---|---|---|---|---|
| `smoke1` | 1 | 24 | expectation calibration | 121/121 |
| `attempt1` | 10 | 240 | failed round (2 transport pauses) | 117/120 (pre-amendment verifier) |
| `probe1` | 1 | 22 | isolate the `self`/L2 pause | calibration only |
| `attempt2` | 10 | 240 | main round | 121/121, zero SQLite mismatches |

`attempt1` had no process failure but two workflows in `self`/L2/`late_commit`
paused at `commit` after a failed `GET /permit`; they were safe pauses with no
effect and no rejection, and the same workflow completed both faults when run
alone. The amendment in protocol section 12 makes the runner record every
exchange failure per step and terminate the service if `/control/stop` is lost.
`attempt2` has no exchange failure outside the injected `attach` step.

`verify_r49.py` re-reads committed effects, stale effects, provisional rows,
duplicates and rejections from each workflow's SQLite file, compares them with
`completion.json` (0 mismatches), and checks 121 criteria over 3 ownership
regimes x 4 levels x 2 faults x 10 seeds.

## 2. Outcome table

C = safe completion, P = safe pause, X = unsafe (duplicate or stale effect).
Each cell is 10 workflows.

| Ownership | Level | Effective | Controller | lost return | late commit |
|---|---|---|---|---|---|
| `self` | L0 | C0 | `clear_pause` | P | P |
| `self` | L1 | C3 | `clear_evidence` | C | X |
| `self` | L2 | C4 | `clear_evidence` | C | C |
| `self` | L3 | C6 | `clear_fenced` | C | C |
| `read_only` | L0 | C0 | `clear_pause` | P | P |
| `read_only` | L1 | C3 | `clear_evidence` | C | X |
| `read_only` | L2 | C3 | `clear_evidence` | C | X |
| `read_only` | L3 | C3 | `clear_evidence` | C | X |
| `unmodifiable` | L0-L3 | C0 | `clear_pause` | P | P |

Duplicate counts: `self`/L1/`late_commit` 10, and `read_only` L1-L3
`late_commit` 10 each. Every other cell has 0 duplicates and 0 stale effects.
Pauses: 20/20 in `self`/L0, 80/80 in `unmodifiable`, 0 elsewhere.

## 3. Cost curve

Measured on the main round. Endpoints are counted from the axes the service
reports at `GET /manifest` (base 5: business write, `permit`, two `manifest`
reads, `state`). Handler lines are counted with `ast` on `r45_service.py`;
controller lines are counted the same way on `r45_client.py`.

| Level | Endpoints | New vs L0 | Service lines (cumulative) | Controller lines | Config items | Requests (median) | Bytes (median) |
|---|---|---|---|---|---|---|---|
| L0 | 5 | 0 | 0 | 7 | 2 | 9 | 36 KB |
| L1 | 7 | +2 (read-only) | 35 (35) | 90 | 2 | 19 | 36 KB |
| L2 | 8 | +3 (one write path) | 22 (57) | 90 | 2 | 19 | 36 KB |
| L3 | 11 | +6 (two write-path groups) | 48 (105) | 41 | 2 | 24.5 | 36 KB |

The controller-side retrofit is constant across service levels: 2 configuration
items (`budget`, `after_initial`), 25 guard lines and 0 lines of business-code
change, as measured in R27. Evidence storage does not discriminate (36 KB at
every level).

## 4. Findings

**L2 is the minimum retrofit that is safe and complete under both faults.**
Under `self`, L0 pauses in both (20/20), L1 completes the lost return but
duplicates 10/10 under a late commit, and L2 completes both without a duplicate.
This reproduces R26's conclusion on the R45 workload: admission plus receipt is
the smallest set of service capabilities that supports recovery (R49's level
numbers follow R45; R26's minimum set is R49's L2). The increment
from L1 to L2 is one endpoint on the write path and 22 handler lines; the
controller does not change between L1 and L2, so the guarantee change is
attributable to the service alone.

**Read-only ownership buys completion but not safety.** Adding closure and
effect reads to a third-party service (L1) recovers the lost return, but L2 and
L3 collapse to the same profile and still duplicate 10/10 under a late commit:
without an atomic admission check the controller cannot prevent the delayed
write. The result is the same for the three requested levels, so "buy more
read-only endpoints" has a flat return above L1.

**Without write access the only safe action is to pause.** All 80
`unmodifiable` workflows pause with 0 duplicates and 0 stale effects, at 9
requests each. The pause is safe but the task never completes: the controller
has no way to distinguish a committed effect from a lost one.

**L3 costs more and adds nothing on these faults.** Staging, fence and finalize
cost 3 more endpoints, 48 more handler lines and 5.5 more requests (24.5 vs 19),
while the outcome is identical to L2. Its advantage appears under a lost request
before commit (R45: C6 completes where C4 pauses); R49 does not re-measure that
cell. The cost curve is therefore not monotone in benefit: L2 is the knee.

**Cost is not where the safety comes from.** The controller is 90 lines at both
L1 and L2 and 41 lines at L3, yet only L2 and L3 are safe in both faults. The
same controller over a weaker service is unsafe; the same controller over a
stronger service is correct. This is the R49 form of the capability argument.

## 5. Differences from pre-registration

No outcome or cost criterion changed. `attempt1` is kept as a failed round
because two safe pauses came from an exchange failure, not from service
behaviour; protocol section 12 records the runner and verifier amendment.

## 6. Paper integration

- Add the ownership x level table and the cost curve; they answer "why not just
  fix the service" with the ownership constraint.
- Use L2 as the named minimum retrofit: one admission endpoint plus a receipt,
  22 handler lines, no controller change.
- Keep the read-only row as the counter-example: more evidence without a write
  path still duplicates.
- Do not claim that CLEAR needs no service change; it needs L2, and R49 prices it.

## 7. Artifacts

- `runs/R49/attempt2/` (main, 240 workflows), `attempt1/` (failed round),
  `probe1/` and `smoke1/` (calibration);
- `runs/R49/attempt2/verification.json` (121 criteria, outcome table, cost curve);
- `scripts/run_r49.py`, `scripts/verify_r49.py`; service and client reused from
  R45 (`scripts/r45_service.py`, `scripts/r45_client.py`).
