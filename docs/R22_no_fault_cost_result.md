# R22 - No-fault cost (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 5 policies x 40 seeds = 200 workflows without fault injection.
Checks passed: 252 checks.
Frozen run: runs/R22/attempt2.
Runner: scripts/run_r22.py.
Checker: scripts/verify_r22.py.
Observed: CLEAR uses 16 HTTP calls per workflow versus 11 for the baseline (+45%); median latency 68.2 ms versus a 64.4-70.9 ms baseline range.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
