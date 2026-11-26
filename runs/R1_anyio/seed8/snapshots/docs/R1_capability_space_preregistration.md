# R1 - Capability space preregistration (protocol)

Date: 2026-10-21.
Status: frozen protocol.
Matrix: 3 sources x 48 capability cells x 5 policies x 1 seed; 10-seed extension (3 x 9 x 240 tasks).
Registered checks: 1,909 checks per source round; 57,230 checks over the 10-seed extension.
Frozen run: runs/R1/attempt2 and runs/R1/seed1..9; runs/R1_anyio/attempt1 and seeds; runs/R1_langchain/attempt2 and seeds.
Runner: scripts/run_r1.py, scripts/run_r1_anyio.py, scripts/run_r1_langchain.py.
Checker: scripts/verify_r1.py.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
