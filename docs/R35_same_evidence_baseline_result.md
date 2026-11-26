# R35 - Evidence-equivalent strong baseline (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 3 conditions x 2 policies x 20 seeds = 120 workflows.
Checks passed: 602 checks.
Frozen run: runs/R35/attempt1.
Runner: scripts/run_r35.py.
Checker: scripts/verify_r35.py.
Observed: With identical evidence the two policies match where no revocation intervenes; in the revocation race verify_retry leaves 3 stale rows in 20/20, while CLEAR pauses with 0 rows.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
