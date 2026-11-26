# R40 - Intent change and pause repair (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 2 scenarios x 3 conditions x 6 runs = 36 runs with deepseek-flash.
Checks passed: 304 checks.
Frozen run: runs/R40/attempt2.
Runner: scripts/run_r40.py.
Checker: scripts/verify_r40.py.
Observed: clear follows the new binding in 6/6 runs with 0 mixed bindings and 0 false completion, retaining one old-seat effect; blind and evidence leave 12 and 11 mixed rows; without fences clear pauses 6/6, and 6/6 recover after the upgrade.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
