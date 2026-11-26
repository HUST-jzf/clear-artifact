# R44 - Equal-capability comparison with atomic key de-duplication (result)

Date: 2026-10-22.
Status: frozen result.
Matrix: 198 tasks: 3 key modes x 3 fault kinds (180) plus 18 binding-change tasks.
Checks passed: 49 checks.
Frozen run: runs/R44/attempt1.
Runner: scripts/run_r44.py.
Checker: scripts/verify_r44.py.
Observed: A versioned key and L2' are both 20/20 safe; a rebuilt key duplicates 20/20; an unversioned key falsely completes 6/6; L2' uses 19-22 requests versus 14 and 36,864 B versus 28,672 B, with a 12% median wall-clock overhead (5%-29% by condition).

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
