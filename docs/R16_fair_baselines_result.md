# R16 - Fair external baselines on the same workflow (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 2 baselines x 2 configurations x 4 faults x 20 seeds = 320 workflows.
Checks passed: 1,027 checks.
Frozen run: runs/R16/attempt2.
Runner: scripts/run_r16.py.
Checker: scripts/verify_r16.py.
Observed: Both baselines match idem_retry cell for cell: 0 duplicates with idempotency and 40 duplicates without; each baseline leaves 80 post-revocation writes per configuration (320 in total).

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
