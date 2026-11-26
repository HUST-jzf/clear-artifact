# Reproducing the reported checks

## 1. Environment

- Windows with PowerShell 7 (the entry script is `.ps1`); a POSIX port is
  straightforward but not shipped.
- Python 3.11 or newer; the pinned wheel was built and tested with CPython
  3.13.
- No network access is needed for the main reproduction: the wheel is local and
  `PIP_NO_INDEX=1` is set by the script.
- For the Z3 model checks, install `z3-solver==5.3.1.0`
  (`requirements.txt`). Everything else in the main reproduction is standard
  library only.

## 2. One command

```powershell
powershell -ExecutionPolicy Bypass -File artifact/run.ps1 -RunDir runs/R10/repro1
```

`run.ps1`:

1. changes to the repository root (it does not depend on the caller's cwd);
2. creates `runs/R10/repro1/env` and installs
   `runs/U07/attempt1/dist/clear_assurance-2.0.0-py3-none-any.whl`
   (`sha256 8fac564ad0599dd8bf276e61e37b6cb410564230398d50b3acef99d61cfcde63`)
   offline with `--no-deps`;
3. runs `artifact/reproduce.py --run-dir runs/R10/repro1`.

It refuses to run if `reproduction.json` already exists in the target
directory, so use a fresh `-RunDir` for each reproduction.

Expected final output:

```json
{"status": "pass", "checks_total": 6749, "checks_passed": 6749, "failed": 0}
```

Acceptance values:

| Item | Expected |
|---|---|
| `runs/R10/repro1/completion.json` → `status` | `pass` |
| `checks_total` / `checks_passed` | 6749 / 6749 |
| `analysis1/verification.json` → `failed` | `[]` |
| `tables.md` sections | R1–R44 |
| Network | not required |
| Secrets | not required; `DEEPSEEK_API_KEY` is never read |

`reproduce.py` first hashes the artifact files and the sealed run records into
`freeze.json`; it then re-runs every `scripts/verify_*.py`, recomputes the
aggregates from the raw per-task JSON / SQLite / JSONL records rather than
trusting runner-produced totals, and compares the totals with
`artifact/expected.json`.

The 93 module-identity checks in R1/R3 and the R3 CLI hash are the only checks
that originally read outside the repository. The module files are mirrored
byte-for-byte under `sources/_installation_mirror/<sha256>` and the checkers
fall back to the mirror when the recorded path is absent; the Temporal CLI
1.9.1 binary is shipped as a split archive under `sources/R3_temporal/cli/parts`
and rebuilt by `sources/R3_temporal/cli/assemble.py` (run.ps1 does this on the
first run; the script verifies the original sha256). The count is
therefore the same on a machine that never hosted the original experiment
environments. Check names, counts and hashes are unchanged.

## 3. Per-suite reproduction

All of the following are offline and standard-library only.

### R38 — fence settlement (280 workflows)

```powershell
python scripts/run_r38.py --attempt attempt1
python scripts/r38_fence_check.py --out runs/R38/attempt1/fence_check.json
python scripts/verify_r38.py --run runs/R38/attempt1
```

Expected verifier total: 1405/1405.

### R42 — unbounded inductive checks for T5/T6 (8 configurations)

```powershell
python formal/t56_model.py --output formal/t56_report.json
python scripts/verify_r42.py --report formal/t56_report.json --out formal/t56_verification.json
```

Expected: 43/43. Requires `z3-solver`.

### R44 — equal-capability comparison (198 tasks)

```powershell
python scripts/run_r44.py --attempt attempt1
python scripts/verify_r44.py --run runs/R44/attempt1 --out runs/R44/attempt1/verification.json
```

Expected: 49/49.

### R17 — finite-state and inductive guard checks

```powershell
python formal/z3_model.py --output formal/z3_report.json
python scripts/verify_r17.py formal/z3_report.json
```

Expected: 21/21.

### R41 — bounded concurrent exploration (2 controllers)

```powershell
python scripts/r41_model_check.py --out runs/R41/attempt1/model_check.json
```

Seven configurations at depths 8 (T5) and 6 (T6); the script exits non-zero
unless every configuration matches the pre-registered reachability result.

### R43 — Atomix original system

The upstream checkout is not redistributed. The checker validates the frozen
summary and the four raw JSON files:

```powershell
python scripts/verify_r43.py --run runs/R43/attempt1 --out runs/R43/attempt1/verification.json
```

Expected: 62/62. Upstream commit `61e411be662bb021634f0e84bc184bf6074905b4`.
To re-run the system itself, obtain that commit and follow
`docs/R43_atomix_protocol.md`.

## 4. Re-running a full family

Each runner writes to `runs/<ID>/<attempt>` and takes a one-seed slice or the
full grid, depending on the family. Examples:

```powershell
python scripts/run_r15.py --attempt attempt1     # 800 workflows, local HTTP + SQLite
python scripts/verify_r15.py --run runs/R15/attempt1
python scripts/run_r34.py --attempt attempt1     # 120 workflows, two controllers
python scripts/verify_r34.py --run runs/R34/attempt1
```

R4 and R14 are one source and one seed per invocation (40 tasks each); the
ten-seed extension is produced with `seed1`–`seed9` directories and summarized
by `scripts/summarize_r4_seeds.py`. Runners and checker names for every family
are listed in `docs/README.md` and in `runs/README.md`.

## 5. Suites that need external systems

These runners are included for completeness. They are not part of the 6749
checks, because they need software that is not vendored or a model endpoint.

| Family | Entry points | Requirement |
|---|---|---|
| R3 | `run_r3_langgraph.py`, `run_r3_temporal.py` | LangGraph 1.2.16, Temporal CLI/server |
| R16 | `run_r16.py`, `r16_temporal.py` | Temporal CLI/server |
| R4/R14 | `run_r4.py`, `r4_holdout.py` | smolagents, Pydantic AI, LlamaIndex, AutoGen Core |
| R27/R28 | `run_r27.py`, `run_r28.py` | MCP Python SDK; two npm MCP servers |
| R39/R40 | `run_r39.py`, `r39_agent.py`, `run_r40.py`, `r40_agent.py` | `DEEPSEEK_API_KEY` (optional `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`) |

Pinned versions and wheel hashes are in `sources/README.md`,
`requirements-external.txt`, and the per-source `wheels_sha256.json` files.

The reproduction does **not** re-run R39/R40 model calls; it recomputes their
criteria from the frozen server records, as the paper states.

## 6. Interpreting the counts

- A "check" is one recomputed comparison against a pre-registered value, not a
  theorem.
- Structural outcomes (completion, duplicate effects, stale rows, false
  completion) enter the checks. Wall-clock and storage values are descriptive
  and machine-dependent.
- The 6,749 total is tied to `reproduce.py` and `expected.json`. If either
  changes, record a new R10 attempt instead of editing the frozen expected
  values.
- `runs/README.md` names the valid round for each family. This repository
  ships those rounds. Only valid rounds enter the tables.

## 7. Portability and frozen bytes

See section 2 for the module mirror. Two further points matter when moving the
repository:

- The English protocol and result records under `docs/` are the frozen versions
  for this release; their SHA-256 values are recorded in the run freezes. They
  contain no development paths, usernames or credentials.
- Do not let an editor or a Git checkout with `core.autocrlf=true` rewrite
  files under `runs/`, `docs/`, `scripts/` or `sources/`: line endings are part
  of the frozen hashes. `.gitattributes` is not shipped because the freeze
  records byte hashes, not normalized text.

## 8. Troubleshooting

- **Long paths on Windows.** Enable long-path support (`git config --system
  core.longpaths true` and the corresponding policy) before cloning.
- **Wheel install fails.** Confirm the file exists at
  `runs/U07/attempt1/dist/clear_assurance-2.0.0-py3-none-any.whl` and that
  `PIP_NO_INDEX=1`. Verify its SHA-256 against the value in section 2.
- **Z3 missing.** Only R42 and R17 need it; the main 6,749-check run replays
  their frozen reports through the verifiers and does not import `z3`.
- **Existing output.** `run.ps1` refuses to overwrite a completed run; choose a
  new `-RunDir`.
- **Line endings.** Do not let an editor rewrite files under `runs/`; the
  reproduction hashes them into `freeze.json` for the record.

## 9. Studies outside the 6,749-check total

Table 4 of the paper also reports R45–R49. Their checkers recompute effects
from each workflow SQLite file. They do not call a model API and do not modify
the frozen directories when `--out` points elsewhere:

```powershell
powershell -ExecutionPolicy Bypass -File artifact/check_table4.ps1
```

| Study | Frozen round | Checker | Expected |
|---|---|---|---|
| R45 capability frontier | `runs/R45/attempt2` | `scripts/verify_r45.py` | 273/273 |
| R46 identity semantics | `runs/R46/attempt1` | `scripts/verify_r46.py` | 111/111 |
| R47 task-level intent | `runs/R47/attempt1` | `scripts/verify_r47.py` | 59/59 |
| R48 cross-layer closure | `runs/R48/attempt2` | `scripts/verify_r48.py` | 13/13 |
| R49 retrofit cost | `runs/R49/attempt2` | `scripts/verify_r49.py` | 121/121 |

Reports are written to `runs/R10/table4-check/`. To execute a study again from
scratch, run the matching `scripts/run_rXX.py` into a new attempt directory.
That path starts local HTTP services and does not need an API key for these
five studies.
