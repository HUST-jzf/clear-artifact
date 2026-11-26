# R30 - Evidence-plane outage (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 2 modes x 2 idempotency settings x 2 faults x 5 policies x 10 seeds = 400 workflows.
Checks passed: 1,289 checks.
Frozen run: runs/R30/attempt1.
Runner: scripts/run_r30.py.
Checker: scripts/verify_r30.py.
Observed: Losing only lifecycle evidence: CLEAR 40/40 safe via the effect index; losing both planes: CLEAR 40/40 paused while the idempotent baseline completes 20/20.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
