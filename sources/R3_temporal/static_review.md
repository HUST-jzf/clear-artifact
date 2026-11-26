# Temporal CLI 1.9.1 / Python SDK 1.34.0 static review (R3 external baseline)

2026-10-21. The CLI archive `temporal_cli_windows_amd64.zip` (SHA-256
`babb6584...8c7589`, 46,408,338 bytes) expands to `cli/temporal.exe` (SHA-256
`c49d7f0d...af3c806`). The five Python SDK wheels are hashed in
`wheels_sha256.json`. They were installed offline into an isolated virtual
environment; no upstream source was modified.

## Reading path and conclusions

1. `temporalio/common.py` `RetryPolicy`: `maximum_attempts` defaults to 0
   (unbounded), `initial_interval` to 1 s and `backoff_coefficient` to 2.0. The
   experiment sets 2 attempts, 10 ms and 1.0, matching the one-recovery budget
   of the LangGraph baseline.
2. `temporalio/worker/_activity.py`: a synchronous activity runs through
   `loop.run_in_executor(input.executor, func, ...)` (around line 884). Python
   cannot forcibly terminate an already running thread. When
   `start_to_close_timeout` fires, the server schedules the next attempt while
   the first thread may still execute and write.
3. The server-side cancellation path in the same file sets a cancellation
   event, but the activity in this experiment does not check it. This matches
   the deployment fact that the original executor may continue after a timeout;
   it is not an artificial weakening.
4. The SDK documentation states that activities are **at-least-once**:
   `temporalio/contrib/strands/README.md` says "Like all Temporal Activities,
   sandbox operations have at-least-once execution". Activity retry alone
   therefore does not make the effect single-write; de-duplication needs a
   business idempotency key.
5. Workflow state is persisted by the Temporal service. What is recovered is
   the workflow event history, not an external effect. Whether the external
   effect was committed still requires a business query.

## Direct constraints on the experiment

- The baseline gets standard Temporal activity retry and durable workflow; no
  per-case tuning is applied.
- With `I=1`, a unique index in the effect store de-duplicates; with `I=0` it
  does not. Idempotency is a baseline capability, not something unique to CLEAR.
- In `late`, the first attempt still writes after its 60 ms timeout and the
  second attempt enters concurrently. This follows directly from
  `start_to_close_timeout` and thread-pool semantics.
- Revocation is written to the effect store when the first attempt finishes;
  the second attempt is not re-qualified, so it exposes a stale permit.
- The local dev server is a single-node, non-production cluster. Results must
  not be extrapolated to Temporal Cloud or to production persistence settings.
- `protobuf`, `nexus-rpc` and `types-protobuf` are dependency closure and do not
  enter the experiment path. Runs do not use the network (the dev server binds
  to 127.0.0.1).
