# Pydantic AI 2.59.0 static review (R4 held-out source)

2026-10-21. Seventeen wheels were downloaded and hashed, then installed offline
into `runs/R4_pydantic_ai/env`. Resolved versions: `pydantic-ai-slim 2.59.0`,
`pydantic 2.14.1`, `anyio 4.15.1`. No upstream source was modified.

## Reading path and conclusions

1. `pydantic_ai/tools.py` `Tool` (around line 352): a dataclass holding
   `function`, `name`, `description`, `function_schema` and similar fields; the
   constructor builds the schema from the function signature.
2. `pydantic_ai/_function_schema.py` `FunctionSchema.call` (around line 81)
   converts `args_dict` into positional/keyword arguments, validates and calls
   the function; async functions are awaited. This is the common tool execution
   path.
3. `pydantic_ai/toolsets/function.py` (around line 836): `FunctionToolset` uses
   `call_func=tool.function_schema.call`, confirming that the adapter goes
   through the framework's real execution path rather than calling the Python
   function directly.
4. `Tool` contains no effect query, executor lifecycle registration or
   termination signal; these are supplied by the host, not inferred from
   Pydantic AI.

## Direct constraints on the experiment

- The adapter registers one `append(operation_id, intent)` function as a `Tool`
  and calls it through `tool.function_schema.call({...}, None)`; there are no
  per-condition branches.
- `append` uses an AnyIO worker thread for the synchronous SQLite write with
  `abandon_on_cancel=True`, so the write can complete after the caller times
  out. This is host timeout semantics, not Pydantic AI cancellation semantics.
- The adapter does not read framework internal state to infer effects;
  `describe`/`effects`/`status` are implemented by the host.
- This source is not a blind hold-out: the authors knew the condition matrix.
- `logfire-api`, `opentelemetry-api`, `genai-prices` are dependency closure and
  do not enter the experiment path; no model or network is configured.
