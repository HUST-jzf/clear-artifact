# R24 - Recoverable pause (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 2 conditions (revocation, evidence blackout) x 4 policies x 20 seeds = 160 workflows.
Checks passed: 512 checks.
Frozen run: runs/R24/attempt1.
Runner: scripts/run_r24.py.
Checker: scripts/verify_r24.py.
Observed: Terminal clear completes 0/20; clear_resume (evidence first) 40/40 safe; clear_replay produces 20 duplicate writes under blackout.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
