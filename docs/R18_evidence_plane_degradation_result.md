# R18 - Evidence-plane degradation (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 6 service configurations (lifecycle x effect index x idempotency) x 2 faults x 5 policies x 20 seeds = 1,200 workflows.
Checks passed: 3,723 checks.
Frozen run: runs/R18/attempt1.
Runner: scripts/run_r18.py.
Checker: scripts/verify_r18.py.
Observed: off+stale: CLEAR 40/40 safe, each retry policy 40 duplicates; off+unavailable: CLEAR 40/40 safe, retries 40 duplicates each, query policy 40 paused; idempotent configurations saturate.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
