# AutoGen Core 0.7.5 static review (R14 extended held-out source)

2026-10-21. Thirteen wheels were downloaded and hashed, then installed offline
into `runs/R4_autogen/env`. Resolved versions: `autogen-core 0.7.5`,
`anyio 4.15.1`. No upstream source was modified.

## Reading path and conclusions

1. `autogen_core/tools/_function_tool.py` `FunctionTool` (from around line 30)
   inherits `BaseTool` and `Component` and builds the argument model from the
   function signature with `get_typed_signature` and
   `args_base_model_from_signature`; it supports both sync and async functions.
2. `run` in the same file (around line 105) splits the argument model into
   kwargs and calls the underlying function; `run_json` parses JSON by the
   argument model and then delegates to `run`. Both paths only pass a
   `CancellationToken`; there is no effect query, lifecycle registration or
   version binding.
3. `CancellationToken` is cooperative: it takes effect only if the called
   function checks it. The adapter's `append` does not, so a caller timeout does
   not stop an already started SQLite write. This matches the host timeout
   semantics of the other R4 sources.
4. `FunctionToolConfig` only serializes source code and name; there is no
   execution log or effect index.

## Direct constraints on the experiment

- The adapter only registers `append(operation_id, intent)` as
  `FunctionTool(name='append')` and calls it through `run_json`; there are no
  per-condition branches.
- The adapter passes an async function that uses
  `anyio.to_thread.run_sync(..., abandon_on_cancel=True)` for the synchronous
  SQLite write.
- `describe`/`effects`/`status`/`reauthorize`/`drain` are provided by the host,
  not by AutoGen.
- This source is not a blind hold-out: the authors knew the condition matrix.
- `protobuf`, `opentelemetry-api`, `pillow`, `jsonref` are dependency closure or
  registration dependencies and do not enter the experiment path; runs do not
  use the network.
