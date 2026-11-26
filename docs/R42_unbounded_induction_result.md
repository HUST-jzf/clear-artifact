# R42 - Unbounded inductive checks for T5/T6 (result)

Date: 2026-10-22.
Status: frozen result.
Matrix: 8 Z3 configurations: T5 (no A6, naive lease, closed lease, atomic admission) and T6 (both, fence only, finalize only, neither).
Checks passed: 43 checks.
Frozen run: runs/R42/attempt1.
Runner: formal/t56_model.py.
Checker: scripts/verify_r42.py.
Observed: t5_no_a6 and t5_lease_naive reach a duplicate; t5_lease_closed and t5_atomic_admit are safe; t6_both is unsat; each single-condition ablation yields a counterexample.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
