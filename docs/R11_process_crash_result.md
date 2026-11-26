# R11 - Real process crash and restart (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 5 conditions x 5 policies x 10 seeds = 250 tasks.
Checks passed: 522 checks.
Frozen run: runs/R11/attempt3.
Runner: scripts/run_r11.py.
Checker: scripts/verify_r11.py.
Observed: CLEAR: 0 duplicates, 0 stale writes and 0 false completion; after a post-commit crash it completes via query, after a pre-commit crash it pauses because the registration is lost.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
