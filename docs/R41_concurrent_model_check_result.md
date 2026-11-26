# R41 - Bounded concurrent model check (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 2 controllers; T5 depth 8, T6 depth 6; 7 configurations.
Checks passed: 14 checks.
Frozen run: runs/R41/attempt1.
Runner: scripts/r41_model_check.py.
Checker: the runner's exit status and its pre-registered reachability table.
Observed: All 7 configurations match the pre-registration: duplicate reachable without A6 and with a naive lease, unreachable with a closed lease or atomic admission; each T6 single-condition ablation reproduces its interleaving.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
