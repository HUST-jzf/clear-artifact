# R26 - Minimal retrofit ladder (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 4 interface levels x 2 faults x 3 policies x 10 seeds = 240 workflows.
Checks passed: 797 checks.
Frozen run: runs/R26/attempt1.
Runner: scripts/run_r26.py.
Checker: scripts/verify_r26.py.
Observed: L2 (admission plus receipt) already gives 20/20 safe completion; the full effect index matters only for query_retry; blind retry duplicates at all four levels.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
