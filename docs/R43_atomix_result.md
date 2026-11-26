# R43 - Atomix original system (result)

Date: 2026-10-22.
Status: frozen result.
Matrix: upstream commit 61e411b; four local experiment groups (b3_irreversible, e5_b2, e5_b3, test suite).
Checks passed: 62 checks.
Frozen run: runs/R43/attempt1.
Runner: the upstream Atomix scripts at the pinned commit.
Checker: scripts/verify_r43.py.
Observed: Tx-Full leaks 0/500 invalid sends and delivers 500/500 valid sends; misclassifying the irreversible effect leaks 300/500; e5_b2 blocks 400 attempts when the frontier stalls and produces 200/200 out-of-order commits when it advances early; e5_b3 shows no duplicate or loss but two crash windows block recovery.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
