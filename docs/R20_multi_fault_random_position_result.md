# R20 - Multiple faults and random fault positions (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 3 campaigns x 2 idempotency settings x 5 policies x 20 seeds = 600 workflows.
Checks passed: 2,821 checks.
Frozen run: runs/R20/attempt1.
Runner: scripts/run_r20.py.
Checker: scripts/verify_r20.py.
Observed: CLEAR: 120/120 safe, 0 false completion; without idempotency, direct and re-authorized retries produce 20 duplicates at one fault point and 40 at two.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
