# R15 - End-to-end workflow (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 2 service configurations x 4 faults x 5 policies x 20 seeds = 800 workflows.
Checks passed: 5,669 checks.
Frozen run: runs/R15/attempt2.
Runner: scripts/run_r15.py.
Checker: scripts/verify_r15.py.
Observed: CLEAR: 0 duplicates and 0 post-revocation writes; 80/80 safe under lost return and late commit, 80/80 paused under both revocation faults.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
