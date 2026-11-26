# R34 - Two concurrent recovery controllers (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 2 faults x 3 mechanisms (unprotected, lease, atomic admission) x 20 seeds = 120 workflows.
Checks passed: 602 checks.
Frozen run: runs/R34/attempt1.
Runner: scripts/run_r34.py.
Checker: scripts/verify_r34.py.
Observed: Under lost-before-commit, the unprotected policy duplicates 20/20; the in-process lease and server-side atomic admission each keep a single row in 20/20.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
