# R18 - Evidence-plane degradation (protocol)

Date: 2026-10-21.
Status: frozen protocol.
Matrix: 6 service configurations (lifecycle x effect index x idempotency) x 2 faults x 5 policies x 20 seeds = 1,200 workflows.
Registered checks: 3,723 checks.
Frozen run: runs/R18/attempt1.
Runner: scripts/run_r18.py.
Checker: scripts/verify_r18.py.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
