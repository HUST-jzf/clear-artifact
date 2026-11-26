# AnyIO 4.12.1 static review receipt

Reviewed `anyio/to_thread.py:25-65` and
`anyio/_backends/_asyncio.py:2444-2502` in the wheel. `run_sync` passes
`abandon_on_cancel` to the backend; the backend creates an internal Future and a
queued WorkerThread inside `CancelScope(shield=not abandon_on_cancel)`. With
`abandon_on_cancel=True`, the outer scope may end while the worker continues;
with the default False, the scope shields cancellation and waits for the
Future. `cancellable` is a deprecated override alias since 4.1. This call chain
means that the outer task ending does not imply that the effect worker ended.

Installation and execution were allowed only after this review. Target calls use
only this fixed path and do not modify source. The receipt is not an automatic
static conclusion for arbitrary AnyIO applications.
