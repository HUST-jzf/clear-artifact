# R19 - Evidence redundancy and receipt binding (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 1,200 redundancy workflows (lifecycle lost/faithful x index three states) + 400 forged-receipt workflows.
Checks passed: 5,089 checks.
Frozen run: runs/R19/attempt2.
Runner: scripts/run_r19.py.
Checker: scripts/verify_r19.py.
Observed: lost+faithful: CLEAR 20/20 safe; lost+stale and lost+unavailable: CLEAR 20/20 paused; forged cells: query_retry 20/20 false completion, CLEAR 20/20 rejects the receipt and pauses.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
