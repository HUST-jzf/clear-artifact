# LlamaIndex Core 0.14.25 static review (R14 extended held-out source)

2026-10-21. Sixty-two wheels were downloaded and hashed, then installed offline
into `runs/R4_llamaindex/env`. Resolved versions: `llama-index-core 0.14.25`,
`anyio 4.15.1`. No upstream source was modified.

## Reading path and conclusions

1. `llama_index/core/tools/function_tool.py` `FunctionTool.from_defaults`
   (around lines 60-130) accepts `fn` or `async_fn`; given `async_fn`, it sets
   `_async_fn = async_fn` and `_fn = async_to_sync(async_fn)`; given only a
   synchronous `fn`, it sets `_async_fn = sync_to_async(fn)`.
2. `call` (around line 335) and `acall` (around line 374) invoke the underlying
   function synchronously or asynchronously and wrap the result in `ToolOutput`
   (`raw_output`, `raw_input`, `blocks`). There is no retry, effect query,
   lifecycle registration or version binding.
3. `ToolMetadata` only describes name, description and argument schema; there
   is no index of committed effects and no executor parent-child registration
   or termination signal.
4. `describe`/`effects`/`status`/`reauthorize`/`drain` are therefore supplied by
   the host in `r4_holdout.py`, not by LlamaIndex.

## Direct constraints on the experiment

- The adapter does one thing: register `append(operation_id, intent)` as a
  `FunctionTool(name='append')` and call it through `acall`; there are no
  per-condition branches.
- The adapter passes an `async_fn` that uses
  `anyio.to_thread.run_sync(..., abandon_on_cancel=True)` for the synchronous
  SQLite write, so the write can complete after the caller times out. This is
  host timeout semantics, not LlamaIndex cancellation semantics.
- The adapter does not read LlamaIndex internal state to infer effects.
- This source is not a blind hold-out: the authors knew the condition matrix.
- `nltk`, `pillow`, `aiohttp`, `sqlalchemy` and similar packages are dependency
  closure and do not enter the experiment path; runs do not use the network.
