# R27 - Middleware integration (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 3 sources x 8 conditions x 5 seeds = 120 workflows through a 25-line decorator.
Checks passed: 617 checks.
Frozen run: runs/R27/attempt2.
Runner: scripts/run_r27.py.
Checker: scripts/verify_r27.py.
Observed: The decorator path matches R4 cell for cell; one wrap point and two configuration fields per source; zero business-code changes.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
