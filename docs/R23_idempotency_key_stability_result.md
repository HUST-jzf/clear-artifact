# R23 - Idempotency-key stability (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 4 policies x 2 faults x 20 seeds = 160 workflows.
Checks passed: 512 checks.
Frozen run: runs/R23/attempt1.
Runner: scripts/run_r23.py.
Checker: scripts/verify_r23.py.
Observed: A stable key produces 0 duplicates; rebuilding the key per attempt produces one duplicate in 40/40 workflows; CLEAR 40/40 safe.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
