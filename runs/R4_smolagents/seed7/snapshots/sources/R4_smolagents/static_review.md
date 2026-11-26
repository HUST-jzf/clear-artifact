# smolagents 1.26.0 static review (R4 held-out source)

2026-10-21. Twenty-nine wheels were downloaded and hashed, then installed
offline into `runs/R4_smolagents/env`. Resolved versions: `smolagents 1.26.0`,
`anyio 4.15.1`. No upstream source was modified.

## Reading path and conclusions

1. `smolagents/tools.py` `Tool`: subclasses declare `name`, `description`,
   `inputs`, `output_type` and implement `forward`; `__init_subclass__` validates
   these attributes and the `forward` signature (around lines 140-226).
2. `Tool.__call__` (around line 231) runs `setup()` on the first call, expands a
   single dict argument into kwargs and calls `forward`. There is no retry,
   effect query or lifecycle registration.
3. `Tool.setup` (around line 251) only sets `is_initialized=True`; there is no
   resource lifecycle or termination signal.
4. The framework provides no index of whether an effect was committed and no
   parent-child executor registration. These are supplied explicitly by the
   host in `r4_holdout.py`, not inferred from smolagents.

## Direct constraints on the experiment

- The adapter does one thing: register `append(operation_id, intent)` as a
  `Tool` and call `forward` through `tool(...)`; there are no per-condition
  branches.
- `Tool.__call__` is synchronous. The adapter calls it on an AnyIO worker thread
  with `abandon_on_cancel=True`, so the underlying function can complete after
  the caller times out. This is host timeout semantics, not smolagents
  cancellation semantics; the paper must distinguish them.
- The adapter does not read smolagents internal state to infer effects;
  `describe`/`effects`/`status` are implemented by the host.
- This source is not a blind hold-out: the authors knew the condition matrix.
- `huggingface_hub`, `pillow`, `rich` and similar packages are dependency
  closure and do not enter the experiment path; runs do not use the network.
