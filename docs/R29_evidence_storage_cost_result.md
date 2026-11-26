# R29 - Evidence storage cost (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 3 scales (25/50/100 workflows), 175 workflows in total.
Checks passed: 566 checks.
Frozen run: runs/R29/attempt1.
Runner: scripts/run_r29.py.
Checker: scripts/verify_r29.py.
Observed: 24,576 B per workflow and 275 B per receipt; growth is strictly linear in the number of steps.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
