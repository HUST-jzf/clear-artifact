# R23 - Idempotency-key stability (protocol)

Date: 2026-10-21.
Status: frozen protocol.
Matrix: 4 policies x 2 faults x 20 seeds = 160 workflows.
Registered checks: 512 checks.
Frozen run: runs/R23/attempt1.
Runner: scripts/run_r23.py.
Checker: scripts/verify_r23.py.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
