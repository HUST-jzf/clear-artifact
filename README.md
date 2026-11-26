# CLEAR experiment repository

Companion repository for the paper *CLEAR: Change-aware Lifecycle Evidence and Admission for Recovery in Trustworthy Agent Tool Calls*.

CLEAR routes recovery of an unknown tool-call result according to the service capability that is actually present: the evidence path, the fenced path, a versioned idempotency key already checked on the write path, or a wait or pause.

This repository contains the reference implementation, the experiment runners and independent checkers, the formal models, the protocol and result records, and the frozen run records needed to recompute the numbers reported in the paper.

## Quick check

Windows, Python 3.11+ (3.13 tested). The main check needs no network.

```powershell
powershell -ExecutionPolicy Bypass -File artifact/run.ps1 -RunDir runs/R10/repro1
```

Expected final line:

```json
{"status": "pass", "checks_total": 6749, "checks_passed": 6749, "failed": 0}
```

The command creates an isolated virtual environment, installs the pinned `clear_assurance-2.0.0` wheel from `runs/U07/attempt1/dist/`, re-runs every shipped verifier in the sealed suite, and recomputes the aggregates from the frozen per-task JSON and SQLite records. It writes `reproduction.json`, `tables.md`, and `analysis1/verification.json` into the new run directory. A completed example is kept in `runs/R10/repro7` (without its virtual environment). See [REPRODUCE.md](REPRODUCE.md).

Studies R45–R49 are reported in the paper and are checked separately. They are not part of the 6,749-check total.

```powershell
powershell -ExecutionPolicy Bypass -File artifact/check_table4.ps1
```

Expected lines: R45 273/273, R46 111/111, R47 59/59, R48 13/13, R49 121/121. The script writes its reports under `runs/R10/table4-check/` and does not modify the frozen run directories.

## Layout

| Path | Contents |
|---|---|
| `src/clear_assurance/` | Reference implementation: evidence, audit, decision, replay, bundle, CLI |
| `tests/` | Unit tests for the core library |
| `examples/` | Synthetic audit and decision inputs |
| `artifact/` | `run.ps1`, `check_table4.ps1`, `reproduce.py`, `expected.json` |
| `scripts/` | Runners, HTTP services, clients, agents, verifiers, model checks |
| `formal/` | Z3 models for T1a/T2/T4 (R17) and T5/T6 (R42), plus the bounded model |
| `docs/` | English protocol and result records, one per experiment |
| `runs/` | Frozen run records used as reproduction input; `README.md` lists the valid rounds |
| `sources/` | Third-party provenance: versions, wheel hashes, static reviews, npm manifests, the pinned Temporal CLI, and a content-addressed mirror of the module files whose hashes the R1/R3 checkers verify |
| `figures/` | Paper figures 1–4 |

## Paper-to-repository map

Identifiers in parentheses match `runs/` and `docs/`.

| Paper item | Where to look |
|---|---|
| Three traces behind one timeout, Figure 1 | `scripts/r15_service.py`, `figures/fig1.png` |
| Capability routing and the guard, Figure 2 | `src/clear_assurance/core.py`, `scripts/r27_guard.py` |
| Settlement protocol, Figure 3 | `scripts/r38_service.py`, `scripts/r38_client.py`, `scripts/r38_fence_check.py` |
| Interfaces and retrofit levels | `scripts/r26_service.py`, `scripts/r38_service.py`, `scripts/run_r49.py`; runs R26, R27, R49 |
| T1a/T2/T4, 21 Z3 checks | `formal/z3_model.py`, `formal/z3_report.json`, `scripts/verify_r17.py` (R17) |
| T5/T6, 43 induction checks | `formal/t56_model.py`, `scripts/verify_r42.py` (R42) |
| Bounded interleavings, depths 8 and 6 | `scripts/r41_model_check.py` (R41) |
| Capability frontier, Figure 4(c) | R45 `attempt2`, 1,760 workflows, `scripts/verify_r45.py` |
| Ablation; dual-controller race | R8; R34 |
| Held-out frameworks; matrix | R4, R14; R1 |
| No-closure; cross-layer; revocation | R38; R48 `attempt2` (320 runs); R35 |
| Workflow baselines, Figure 4(b); frontier gating | R3 (LangGraph, Temporal); R36 |
| Real model, Figure 4(a) | R39 `attempt4` (28/28, 19/28, 8/28). Recomputation is offline; a fresh sample needs `DEEPSEEK_API_KEY` and will vary |
| Intent; identity; ownership | R40; R46 `attempt1` (700 runs); R47 `attempt1` |
| Crash; payments | R11; R25 |
| Retrofit cost, Table 5; paired skeleton; latency; evidence-surface outage | R49 `attempt2`; R44; R7; R30 |
| Integration cost; fault-free cost; concurrency | R27; R22; R21 |
| One-command recomputation, 6,749 checks | `artifact/run.ps1`, `artifact/reproduce.py`, `artifact/expected.json` (R10) |

## What is included

- The code used to run and check the experiments cited in the paper, including runners that need external systems (LangGraph, Temporal, MCP servers, a DeepSeek-compatible API).
- The frozen records for those experiments, at the rounds named in `runs/README.md`.
- The pinned CLEAR 2.0.0 wheel used by the reproduction entry.
- Third-party versions, wheel hashes, static reviews, and npm manifests under `sources/`.

Most checks read only files inside this repository. A small group of module-identity checks (93 in R1/R3) and the Temporal CLI hash in R3 originally read files from the experiment virtual environments. Those module files are shipped byte-identically in `sources/_installation_mirror/<sha256>`; `verify_r1.py`, `verify_r3.py`, and `verify_r3_temporal.py` use the mirror when the recorded path is absent. The Temporal CLI 1.9.1 binary is 152 MiB, above GitHub's 100 MiB file limit, so it is stored as a 43 MiB deflate archive split into 1 MiB pieces under `sources/R3_temporal/cli/parts`. `artifact/run.ps1` calls `sources/R3_temporal/cli/assemble.py` to join and unpack them into `sources/R3_temporal/cli/temporal.exe` before the checks. The unpacked file is the original binary, sha256 `c49d7f0d9f6a7ae5aed3b97a259070c1cee7bf7e7543be9b4c602109caf3c806`; `assemble.py` verifies this hash and stops on any mismatch.

## What is not included

- Virtual environments, `__pycache__`, and third-party wheels or npm packages. They are reinstalled from pinned versions. The pinned Temporal CLI is included as pieces and joined before the R3 hash check.
- The upstream Atomix checkout for R43 (commit `61e411b`).
- Credentials and API keys. R39 and R40 require `DEEPSEEK_API_KEY` only when those model runs are executed again. The shipped records contain transcripts and no keys.
- Calibration rounds, infrastructure-failure rounds, and exploratory pilot families that the paper does not cite.
- Optional model-paraphrase subsets (`R46/llm1`, `R47/llm1`, `R48/llm1`). The paper reports the scripted rounds: 700 identity runs, 72 ownership runs, and 320 cross-layer runs.

## Machine notes

Paths that pointed outside this repository were replaced with placeholders. The reproduction reads the frozen records and does not issue new target calls. Running the model study again needs an API key, and a new sample will vary because that API call carries no seed.

## License

MIT for the code in this repository. Third-party software named in `sources/` keeps its own license; only provenance metadata is redistributed.
