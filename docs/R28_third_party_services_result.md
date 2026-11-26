# R28 - Third-party MCP servers (result)

Date: 2026-10-21.
Status: frozen result.
Matrix: 2 npm MCP servers x 2 faults x 4 policies x 20 seeds = 320 workflows.
Checks passed: 1,922 checks.
Frozen run: runs/R28/attempt4.
Runner: scripts/run_r28.py.
Checker: scripts/verify_r28.py.
Observed: CLEAR: 40/40 safe when responses are lost and 40/40 paused when requests are not delivered; blind retry duplicates 20/20 on sqlite and 0/20 on memory (content-level de-duplication).

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
