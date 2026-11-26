# R31 - Cross-tenant receipt binding (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 100 workflows plus one donor workflow.
Checks passed: 328 checks.
Frozen run: runs/R31/attempt1.
Runner: scripts/run_r31.py.
Checker: scripts/verify_r31.py.
Observed: CLEAR 20/20 rejects the cross-workflow receipt and pauses; query_retry 20/20 falsely completes the step.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
