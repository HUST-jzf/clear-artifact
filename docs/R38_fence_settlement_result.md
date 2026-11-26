# R38 - Fence settlement (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 2 closure forms x 2 faults x 3-4 policies x 20 seeds = 280 workflows, plus a five-step settlement ablation.
Checks passed: 1,405 checks.
Frozen run: runs/R38/attempt1.
Runner: scripts/run_r38.py.
Checker: scripts/verify_r38.py.
Observed: Without closure evidence, clear pauses 20/20 in both cells; clear_fenced is 20/20 safe in both and rejects every late write; blind retry duplicates 20/20 in the late-write cell.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
