# R32 - Post-hoc audit of frozen artifacts (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 5 frozen groups, 1,001 workflows, read-only.
Checks passed: 48 checks.
Frozen run: runs/R32/attempt4.
Runner: scripts/run_r32.py.
Checker: scripts/verify_r32.py.
Observed: Reconstructed per-workflow rows, duplicates, stale writes and unbound receipts match the run records with zero differences; the audit also exposed the R21 reauthorize defect.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
