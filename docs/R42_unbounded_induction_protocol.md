# R42 - Unbounded inductive checks for T5/T6 (protocol)

Date: 2026-10-22.
Status: frozen protocol.
Matrix: 8 Z3 configurations: T5 (no A6, naive lease, closed lease, atomic admission) and T6 (both, fence only, finalize only, neither).
Registered checks: 43 checks.
Frozen run: runs/R42/attempt1.
Runner: formal/t56_model.py.
Checker: scripts/verify_r42.py.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
