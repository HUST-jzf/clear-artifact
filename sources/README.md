# Source provenance

All third-party sources were downloaded as pinned wheels, hashed and reviewed
before being installed into an isolated virtual environment. Upstream source was
never modified.

| Directory | Source | Version | Key artifacts |
|---|---|---|---|
| `U02_langchain_core_1_0_0/` | LangChain Core | 1.0.0 | `wheels_sha256.json`, `receipt.json`, `review/`, `install.log` |
| `U04_anyio_4_12_1/` | AnyIO | 4.12.1 | `wheels_sha256.json`, `static_review.md`, `install.log` |
| `U05_mcp_1_26_0/` | MCP Python SDK | 1.26.0 | `wheels_sha256.json`, `static_review.md` |
| `R3_langgraph/` | LangGraph + SQLite checkpointer (external baseline) | 1.2.16 / 3.1.2 | `wheels_sha256.json`, `static_review.md` |
| `R3_temporal/` | Temporal CLI + Python SDK (external baseline) | CLI 1.9.1 / Server 1.32.0 / SDK 1.34.0 | `cli/temporal.exe`, `wheels_sha256.json`, `static_review.md` |
| `R4_smolagents/` | smolagents (held-out source) | 1.26.0 | `wheels_sha256.json`, `static_review.md` |
| `R4_pydantic_ai/` | Pydantic AI (held-out source) | 2.59.0 | `wheels_sha256.json`, `static_review.md` |
| `R4_llamaindex/` | LlamaIndex Core (R14 extended held-out source) | 0.14.25 | `wheels_sha256.json`, `static_review.md` |
| `R4_autogen/` | AutoGen Core (R14 extended held-out source) | 0.7.5 | `wheels_sha256.json`, `static_review.md` |
| `_installation_mirror/` | Content-addressed copies of the module files hashed by R1/R3 | - | one file per SHA-256 |

Rules:

- Wheels and virtual environments are not redistributed; only hashes and review
  notes are shipped. Install the pinned versions offline with `--no-index`.
- New sources use a new directory and a new protocol; frozen sources are never
  overwritten.
- The adapter boundaries and limits are documented in the corresponding
  experiment protocol records. These sources are not blind hold-outs: the
  authors knew the condition matrix.
