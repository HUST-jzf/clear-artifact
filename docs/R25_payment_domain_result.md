# R25 - Payment-domain replication (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 2 idempotency settings x 2 faults x 5 policies x 20 seeds = 400 workflows on a 4-step payment workflow.
Checks passed: 1,571 checks.
Frozen run: runs/R25/attempt1.
Runner: scripts/run_r25.py.
Checker: scripts/verify_r25.py.
Observed: CLEAR: 80/80 safe and 0 duplicate charges; without idempotency, both direct-retry policies duplicate 40 workflows each (amounts double).

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
