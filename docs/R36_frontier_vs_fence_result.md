# R36 - Applicability of frontier gating versus fence settlement (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 2 service forms x 2 faults x 4 policies x 20 seeds = 320 workflows.
Checks passed: 1,602 checks.
Frozen run: runs/R36/attempt2.
Runner: scripts/run_r36.py.
Checker: scripts/verify_r36.py.
Observed: When the runtime can buffer, frontier gating and fence settlement are both 20/20 safe; when it cannot, frontier gating pauses in both cells while fence settlement is 20/20 safe in both.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
