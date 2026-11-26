# LangGraph 1.2.16 static review (R3 external baseline)

2026-10-21. Forty-two wheels were downloaded and hashed in
`wheels_sha256.json`, then installed offline into an isolated virtual
environment. Resolved versions: `langgraph 1.2.16`,
`langgraph-checkpoint-sqlite 3.1.2`, `langchain-core 1.6.12`. No upstream source
was modified.

## Reading path and conclusions

1. `langgraph/pregel/_loop.py` `after_tick` collects the `writes` of each task
   at the end of a superstep and then calls `_put_checkpoint` once per
   superstep (the comments say "finish superstep" and "`_put_checkpoint` is
   called once per superstep").
2. The same file's scheduling and recovery logic reloads the writes of completed
   tasks from the last checkpoint and re-executes incomplete tasks. Side effects
   inside a node are not part of the checkpoint, so a node that fails after
   writing but before the superstep ends has no record that the effect was
   committed.
3. `langgraph/checkpoint/sqlite/__init__.py` `SqliteSaver.put` serializes
   channel values, pending writes and metadata into SQLite. It stores **graph
   state**, not effects in external systems.
4. `SqliteSaver.from_conn_string` uses
   `sqlite3.connect(..., check_same_thread=False)`; it is a lightweight local
   implementation, not a remote durable service.
5. These modules expose no "query external effects by operation id" and no
   executor lifecycle registration or closure. The `langchain_core` tool layer
   does not either.

## Direct constraints on the experiment

- The checkpoint granularity is a superstep, not an external commit inside a
  node. `lost` and `late` faults happen after the in-node commit and before the
  checkpoint, so recovery can only re-run the node.
- Re-running on recovery is LangGraph's defined behavior; the experiment neither
  weakens the baseline nor injects extra failures.
- The baseline has no effect query, lifecycle closure, re-authorization or
  atomic admission. Fixing `Q=1, C=1` only gives it the most favorable
  information condition; it does not use those capabilities.
- The R3 conclusion therefore applies to durable checkpoint/resume as a
  recovery mechanism, not to systems such as Temporal with activity semantics
  and retry policies. Temporal has its own protocol.
- `sqlite_vec`, `langgraph_prebuilt`, `langsmith` and similar packages are
  dependency closure and do not enter the experiment path. `langsmith` is not
  configured to report and runs do not use the network.
