# R4 - Held-out agent frameworks (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 2 sources (smolagents 1.26.0, Pydantic AI 2.59.0) x 8 conditions x 5 policies x 10 seeds = 400 tasks per source.
Checks passed: 140 checks per single-seed round; 149 checks in the 10-seed summary.
Frozen run: runs/R4_smolagents/attempt1 and seed1..9; runs/R4_pydantic_ai/attempt1 and seed1..9; runs/R4_seeds/attempt1.
Runner: scripts/run_r4.py.
Checker: scripts/verify_r4.py.
Observed: Both sources are cell-for-cell identical: CLEAR 60/80 safe, 20 paused, 0 duplicates, 0 stale; idem_retry 50 duplicates and 10 stale.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
