# MCP Python SDK 1.26.0 static review

2026-10-21. Thirty wheels were downloaded to `wheels/` and hashed in
`wheels_sha256.json`, then installed offline into an isolated virtual
environment. Resolved versions: mcp 1.26.0, anyio 4.15.1, pydantic 2.14.1,
pydantic-core 2.50.1. No upstream source was modified.

## Reading path and conclusions

1. `mcp/client/session.py` `ClientSession.call_tool` builds a `CallToolRequest`
   and calls `send_request` directly; there is no additional cancellation
   propagation logic.
2. `mcp/shared/session.py` `BaseSession.send_request` allocates an increasing
   request id, registers `_response_streams[request_id]` and waits on its own
   response stream; a timeout maps to `McpError`. The `finally` block only
   cleans up the response stream. It **does not send
   `notifications/cancelled` when the caller cancels**. Local task cancellation
   therefore abandons the response while the server-side in-flight request
   continues.
3. `_receive_loop` in the same file calls `cancel()` on
   `_in_flight[request_id]` only when a `CancelledNotification` arrives. The
   protocol layer has cancellation semantics, but this client API does not send
   them automatically.
4. `mcp/server/lowlevel/server.py` records and suppresses duplicate responses
   when a request is cancelled, showing that the server does handle
   cancellation notifications. The "plain cancellation" condition in the
   experiment therefore uses an explicit server-side `cancel` tool instead of
   claiming that client task cancellation propagated.
5. `mcp/server/fastmcp/utilities/func_metadata.py`: when `fn_is_async` is true
   it awaits `fn(...)`; a synchronous function runs synchronously on the event
   loop thread. To keep the service loop able to handle concurrent requests,
   the experiment tools are async and delegate the real effect work to
   `anyio.to_thread.run_sync`.
6. `mcp/client/stdio/__init__.py` `stdio_client` starts the server process via
   `anyio.open_process` and uses in-memory streams. The experiment starts a
   separate process per task and records stderr separately.

## Direct constraints on the experiment

- A client-side initial timeout only means the caller stopped waiting; it does
  not mean the server did not execute. CLEAR must read the server `status` and
  `effects` and cannot treat the client ending as effect termination.
- The server `cancel` tool is only a single-mechanism baseline; its return value
  is not proof of effect termination.
- `closed_registration` and `registration_complete` are trusted server
  declarations, not something inferred from an arbitrary MCP server. The
  unregistered background task in M08 is deliberately excluded from the member
  table.
- This source shares the anyio dependency chain with U04, but the versions and
  deployment forms differ (cross-process protocol versus in-process threads).
  The paper must not present them as independent runtime implementations.
