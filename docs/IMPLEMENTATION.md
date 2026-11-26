# CLEAR Assurance 2.0.0

CLEAR — Change-aware Lifecycle Evidence and Admission for Recovery — is an installable
research tool for scoped evidence audit, deployment qualification and guarded recovery of
single-agent tool calls. Python 3.11+; the core has no third-party runtime dependencies.
Installing the package does not publish, deploy or call anything.

Version 2.0.0 is the evaluation artifact for this paper. It keeps the
1.0.0 commands and adds multi-run conformance replay. Historical frozen evidence that uses
the pre-1.0 identifier `spg` is accepted through an explicit alias and is never rewritten.

## Install and run

```powershell
python -m pip install --no-deps --no-build-isolation .
clear-assure --version
clear-assure audit --input examples/audit.json --output out/audit-bundle.json
clear-assure decide --input examples/decision.json --output out/decision-bundle.json
clear-assure verify --input out/audit-bundle.json
clear-assure replay --run <frozen-run-directory> --output out/replay-bundle.json
clear-assure conformance --input conformance.json --output out/conformance-bundle.json
```

`conformance.json` lists named run directories, e.g.
`{"runs": {"langchain": "../runs/U03/attempt1", "anyio": "../runs/U04/attempt8", "mcp": "../runs/U05/attempt3"}}`.
All outputs are new files; existing outputs are rejected, not overwritten. The examples are
synthetic. `replay` reads a frozen recovery run with `result.json`/`native.json` per task and
recomputes every recorded decision from the same observation prefix; it rejects unsupported
schemas instead of guessing.

## Commands

| Command | Input | Output |
|---|---|---|
| `audit` | Ordered guard/effect observations with declared completeness | covered / uncovered / no_effect / unknown with witnesses |
| `decide` | Origin binding, current manifest, capabilities, qualification and observations | Next action (`wait/query/cancel/qualify/retry/complete/pause`), reason, support |
| `replay` | Frozen run directory | Per-task decision replay and mismatch list |
| `conformance` | Named frozen runs (multi-source) | Aggregated replay, per-source counts and mismatch list |
| `verify` | Audit, decision, replay or conformance bundle | Digest and semantic replay result |

## Decision rules

A recovery action is permitted only when all of the following hold:

1. the original root and every declared descendant executor are actually terminal;
2. a later complete effect query for the original operation binding is empty;
3. the current deployment manifest still matches the manifest pinned at the original call,
   or a fresh qualification succeeds after an observed change;
4. the current route is a supported mode, keeps registration closed, allows the write and
   targets the same effect namespace.

A bound positive receipt confirms completion immediately. After one retry returns `accepted`,
the controller may only wait for that execution and query a positive receipt; it never retries
again from an empty query. Missing executor handles, an open registration scope or a changed
manifest without requalification stop the controller instead of rewriting.

## Evidence and adapter boundary

The core consumes a source-neutral schema: operation context, pinned manifest, current
manifest, declared route, capabilities and ordered observations. Adapters are thin and
explicit; the tool does **not** discover framework semantics automatically. Three real
sources were integrated in the research harness: LangChain Core 1.0.0 (`StructuredTool.ainvoke`),
AnyIO 4.12.1 (`to_thread.run_sync` cancellation scope) and MCP Python SDK 1.26.0 (stdio tool
calls). Only the MCP source was driven end-to-end by this installed 1.0.0 wheel; the other two
are reproduced by deterministic replay of their frozen evidence.

## Limits

Worker lifecycle closure, complete effect snapshots and cooperative cancellation are
**host premises**, not properties inferred from arbitrary Python or remote services. The tool
does not provide remote atomic leases, adversarial-provider completeness, general effect
inference or full-program guarantees. Bundles are not signed; verification detects internal
inconsistency and rehashed false verdicts, not a forged but internally consistent source.
Action counts and local timings are descriptive, not an end-to-end performance claim.
