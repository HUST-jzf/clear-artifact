# R14 - Extended held-out agent frameworks (protocol)

Date: 2026-10-21.
Status: frozen protocol.
Matrix: 2 sources (LlamaIndex Core 0.14.25, AutoGen Core 0.7.5) x 8 conditions x 5 policies x 10 seeds = 400 tasks per source.
Registered checks: 141 checks per single-seed round; 149 checks in the 10-seed summary.
Frozen run: runs/R4_llamaindex/attempt2 and seed1..9; runs/R4_autogen/attempt2 and seed1..9; runs/R14_seeds/attempt2.
Runner: scripts/run_r4.py.
Checker: scripts/verify_r4.py.

Detailed per-task records are in the frozen run directory. The checker
recomputes every reported number from those records; the counts above are
the ones compared by the artifact reproduction.
