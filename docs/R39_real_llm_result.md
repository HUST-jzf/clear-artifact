# R39 - Real LLM tool-use coordination (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 3 strategies x (4 no-fault + 4 faults x 6) = 84 runs with deepseek-flash.
Checks passed: 431 checks.
Frozen run: runs/R39/attempt4.
Runner: scripts/run_r39.py.
Checker: scripts/verify_r39.py.
Observed: Safe/duplicate/incomplete: blind 8/17/3, evidence 19/1/8, clear 28/0/0; all 12 late writes under clear are rejected by stale_fence.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
