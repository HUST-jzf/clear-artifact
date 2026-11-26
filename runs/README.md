# Frozen run directory

Each `runs/<ID>/<attempt>` directory is a frozen execution record and must not
be overwritten or edited in place. The table lists the valid round for each
family; the public artifact ships those rounds, the pinned CLEAR 2.0.0 wheel in
`U07/attempt1`, and the reproduction record in `R10/attempt49`.

| Family | Valid round | Main artifacts |
|---|---|---|
| R1 | `attempt2` plus `seed1..9` (three sources) | `freeze.json`, `snapshots/`, `analysis1/verification.json` |
| R2 | `R2_mcp/attempt1`, `R2_anyio/attempt1`, `R2_langchain/attempt2` | `completion.json`, `verification.json` |
| R3 | `R3_langgraph/attempt2`, `R3_temporal/attempt3` | `completion.json`, `verification.json` |
| R4 | `smolagents/attempt1` + seeds, `pydantic_ai/attempt1` + seeds | `freeze.json`, `analysis1/verification.json` |
| R14 | `llamaindex/attempt2` + seeds, `autogen/attempt2` + seeds | `freeze.json`, `analysis1/verification.json` |
| R5 | `attempt1` | `completion.json`, `verification.json` |
| R7 | `attempt2` | `completion.json`, `verification.json` |
| R8 | `attempt3` | `completion.json`, `verification.json` |
| R9 | `attempt1` | `issues.json`, `audit.json`, `table.md` |
| R10 | `attempt49` | `completion.json`, `reproduction.json`, `tables.md` |
| R11 | `attempt3` | `verification.json` |
| R13 | `R13_anyio/attempt1`, `R13_langchain/attempt1` | `verification.json` |
| R15 | `attempt2` | `completion.json`, `verification.json` |
| R16 | `attempt2` | `completion.json`, `verification.json` |
| R17 | `formal/z3_report.json` | `formal/z3_verification.json` |
| R18 | `attempt1` | `completion.json`, `verification.json` |
| R19 | `attempt2` | `completion.json`, `verification.json` |
| R20 | `attempt1` | `completion.json`, `verification.json` |
| R21 | `attempt9` | `completion.json`, `verification.json` |
| R22 | `attempt2` | `completion.json`, `verification.json` |
| R23 | `attempt1` | `completion.json`, `verification.json` |
| R24 | `attempt1` | `completion.json`, `verification.json` |
| R25 | `attempt1` | `completion.json`, `verification.json` |
| R26 | `attempt1` | `completion.json`, `verification.json` |
| R27 | `attempt2` | `completion_<source>.json`, `verification.json` |
| R28 | `attempt4` | per-task `memory.jsonl` / `store.db` / `proxy.json`, `verification.json` |
| R29 | `attempt1` | byte accounting, `verification.json` |
| R30 | `attempt1` | `verification.json` |
| R31 | `attempt1` | `completion.json`, `verification.json` |
| R32 | `attempt4` | `audit.json`, `verification.json` |
| R33 | `attempt2` | `completion.json`, `verification.json` |
| R34 | `attempt1` | per-task `result.json`, `verification.json` |
| R35 | `attempt1` | per-task `result.json`, `verification.json` |
| R36 | `attempt2` | per-task `result.json`, `verification.json` |
| R38 | `attempt1` | per-task `result.json`, `fence_check.json`, `verification.json` |
| R39 | `attempt4` | per-run transcript and result, `verification.json` |
| R40 | `attempt2` | per-run transcripts and result, `verification.json` |
| R41 | `attempt1` | `model_check.json` (7 configurations) |
| R42 | `attempt1` | `t56_report.json`, `verification.json` |
| R43 | `attempt1` | `result.json`, `atomix/*.json`, `verification.json` |
| R44 | `attempt1` | `completion.json`, `verification.json` |
| U07 | `attempt1` | pinned wheel, `conformance-bundle.json`, `verification.json` |
| R45 | `attempt2` | 1,760 workflows, `completion.json`, `verification.json` |
| R46 | `attempt1` | 700 runs, `completion.json`, `verification.json` |
| R47 | `attempt1` | 72 runs, `completion.json`, `verification.json` |
| R48 | `attempt2` | 320 runs, `completion.json`, `verification.json` |
| R49 | `attempt2` | 240 workflows, `completion.json`, `verification.json` |

Calibration and infrastructure-failure rounds are not part of this repository.
The rounds above are the ones cited by the paper. R45–R49 are checked by
`artifact/check_table4.ps1` and are outside the 6,749-check R10 total.
`freeze.json`, `installation.json`, and `completion.json` are frozen records;
`failure.json`/`aborted.json` would be failure evidence.
