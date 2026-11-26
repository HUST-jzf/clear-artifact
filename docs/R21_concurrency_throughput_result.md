# R21 - Concurrency and throughput (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 8 and 32 workers x 2 idempotency settings x 2 faults x 5 policies x 20 seeds = 800 workflows.
Checks passed: 2,489 checks.
Frozen run: runs/R21/attempt9.
Runner: scripts/run_r21.py.
Checker: scripts/verify_r21.py.
Observed: CLEAR: 160/160 safe, matching the serial R18 cells; throughput rises from 8.8 to 23.5 workflows/s and p95 from 1.67 s to 2.17 s.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
