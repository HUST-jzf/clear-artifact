# Reproduction entry

| File | Purpose |
|---|---|
| `run.ps1` | Creates an isolated venv, installs the pinned CLEAR 2.0.0 wheel offline, runs `reproduce.py` |
| `reproduce.py` | Re-runs every verifier and recomputes all aggregates from the frozen records |
| `expected.json` | Pre-registered expected values for R1–R44 |

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File artifact/run.ps1 -RunDir runs/R10/repro1
```

The script refuses to overwrite an existing `reproduction.json`. Outputs are
written to the chosen `-RunDir`:

- `reproduction.json` — status, check totals, full check list;
- `tables.md` — recomputed tables for R1–R44;
- `analysis1/verification.json` — same check list, verifier layout;
- `freeze.json` and `installation.json` — hashes of the artifact, the wheel and
  the sealed run records, plus the Python environment used.

See `../REPRODUCE.md` for acceptance values and per-suite commands.
