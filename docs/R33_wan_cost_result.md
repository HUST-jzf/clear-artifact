# R33 - WAN cost (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 3 RTT settings (1/20/80 ms) x 5 policies x 10 seeds = 150 workflows.
Checks passed: 127 checks.
Frozen run: runs/R33/attempt2.
Runner: scripts/run_r33.py.
Checker: scripts/verify_r33.py.
Observed: Median difference 22.4 / 158.4 / 607.2 ms at 1/20/80 ms; safety unchanged. The structural cost is five extra round trips.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
