# R24 - Recoverable pause (protocol)

Date: 2026-10-21.
Status: frozen protocol.
Matrix: 2 conditions (revocation, evidence blackout) x 4 policies x 20 seeds = 160 workflows.
Registered checks: 512 checks.
Frozen run: runs/R24/attempt1.
Runner: scripts/run_r24.py.
Checker: scripts/verify_r24.py.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
