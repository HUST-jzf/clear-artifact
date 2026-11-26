# R2 - Random-fault campaign (protocol)

Date: 2026-10-21.
Status: frozen protocol.
Matrix: 3 sources x 5 random fault modes x 5 policies x 20 seeds = 1,500 tasks.
Registered checks: 2,512 / 2,511 / 2,513 checks on the three sources.
Frozen run: runs/R2_mcp/attempt1, runs/R2_anyio/attempt1, runs/R2_langchain/attempt2.
Runner: scripts/run_r2.py.
Checker: scripts/verify_r2.py.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
