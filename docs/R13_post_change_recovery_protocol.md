# R13 - Recovery after deployment change (protocol)

Date: 2026-10-21.
Status: frozen protocol.
Matrix: 2 sources (AnyIO, LangChain) x 4 change modes x 5 policies x 20 seeds = 800 tasks.
Registered checks: 1,859 (AnyIO) and 1,861 (LangChain) checks.
Frozen run: runs/R13_anyio/attempt1, runs/R13_langchain/attempt1.
Runner: scripts/run_r13.py.
Checker: scripts/verify_r13.py.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
