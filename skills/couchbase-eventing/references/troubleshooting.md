# Eventing troubleshooting

## Contents

- [Diagnostic workflow](#diagnostic-workflow)
- [Function not triggering](#function-not-triggering)
- [Processing slowly / backlog growing](#processing-slowly--backlog-growing)
- [High failure count](#high-failure-count)
- [Handler runs but produces wrong results](#handler-runs-but-produces-wrong-results)
- [Timer not firing](#timer-not-firing)
- [Eventing service memory pressure](#eventing-service-memory-pressure)
- [Eventing in an XDCR topology](#eventing-in-an-xdcr-topology)

## Diagnostic workflow

1. **Start with the three headline statistics** shown per deployed function on the Eventing page (updated every 10 seconds, with rate charts lagged by 30 seconds):
   - **success** — processed invocations, including timer callbacks
   - **failure** — failures while processing the function code
   - **timeout** — invocations that hit a timeout condition

2. **Pull the full statistics** from an Eventing node. The endpoints are per-node and bound to localhost on port 8096; aggregate across nodes yourself.

   ```
   curl http://<user>:<pass>@localhost:8096/api/v1/stats?type=full
   curl http://<user>:<pass>@localhost:8096/getExecutionStats?name=<function_name>
   curl http://<user>:<pass>@localhost:8096/getLatencyStats?name=<function_name>
   curl http://<user>:<pass>@localhost:8096/getFailureStats?name=<function_name>
   ```

   `type=full` adds `dcp_event_backlog_per_vb`, `doc_timer_debug_stats`, `latency_stats`, `plasma_stats`, and `seqs_processed`; omitting it leaves them out. Events-remaining figures are what tell you whether the function is keeping up.

   Reading statistics or application logs requires **Full Admin** or **Eventing Full Admin**.

3. **Check the state.** `deployment_status: false` means undeployed. `processing_status: false` on a deployed function means paused.

4. **Read the application log** — the function's own `<function_name>.log`, surfaced in the UI's Log view combined across Eventing nodes. Handler exceptions are logged per invocation, which is where the actual error text lives.

Source: [Statistics](https://docs.couchbase.com/server/current/eventing/eventing-statistics.html)

## Function not triggering

**Is it deployed and running?** Undeployed processes nothing; paused holds the checkpoint but processes nothing. Deploy or resume as appropriate.

**Does the Listen To Location match where documents are actually written?** The `bucket.scope.collection` in the configuration must match exactly. A document written to `my-scope.orders` will not trigger a function listening on `_default._default`. If the Listen To Location uses a `*` wildcard, confirm the wildcard actually covers the collection in question.

**Does the mutation type match the handler you defined?** `OnUpdate` fires on creates and updates. `OnDelete` fires on deletes *and* on TTL expiries, with `options.expired` distinguishing them. If documents are being deleted and only `OnUpdate` exists, nothing fires.

**Is there a backlog?** A large events-remaining figure means mutations are queued and the function is processing, just slowly. Go to the next section.

**Was it deployed with Feed Boundary "From now"?** Then pre-existing documents were never processed, and never will be under that deployment.

## Processing slowly / backlog growing

**The handler is too slow.** The usual culprits, in order:

- SQL++ inside the handler, especially without a covering index, and especially if result sets are not closed. Every mutation is a Query Service round trip.
- `curl()` calls to a slow external service.
- Large document reads through bindings.

Fixes: replace single-document SQL++ lookups with bucket-alias KV reads; always call `close()` on result sets; move slow external calls to a queue-and-process pattern where the handler writes a work-order document.

**Not enough workers.** `worker_count` defaults to **1**. Raise it (recommended maximum 64) using pause → update → resume so the checkpoint survives. Remember the cluster-wide total is `worker_count` times the number of Eventing nodes running the function — and on **8.0+**, `num_nodes_running` may be limiting that number.

**The source mutation rate exceeds what Eventing can process.** This is a scaling ceiling, not a tuning problem. Add Eventing nodes, or move to an SDK-based DCP consumer that can scale horizontally outside the cluster (`couchbase-app-integration`).

## High failure count

Get the error text from the function's application log — failures are logged per invocation.

| Error shape | Cause | Fix |
|---|---|---|
| `TypeError: cannot read property X of undefined` | Handler does not guard against missing fields | Add `if (!doc.field) return;` guards at the top |
| Reading a document that has been deleted | Handler reads a binding by key without checking | `var d = binding[key]; if (d) { ... }` — a missing document returns `undefined`, it does not throw |
| Keyspace not found in a SQL++ statement | Wrong bucket/scope/collection path, or a missing backtick on a name with special characters | Verify the keyspace path and escaping |
| SQL++ transpilation errors | `//` comment before the terminating semicolon of a multiline statement, or `$meta.id` used directly | Use `/* */` comments; assign `var id = meta.id;` first |
| SQL++ DML rejected against the source bucket | Recursion guard — DML cannot manipulate documents in the bucket the function listens to | Write back through the bucket alias KV map instead |
| `CurlError` / connection refused | URL binding host unreachable, or `enable_curl` not set for this scope | Check connectivity from Eventing nodes; check the binding; on 8.0+ check bucket/scope-level `enable_curl` |
| Execution timeout | Handler exceeded Script Timeout (default 60 s) | Find the slow operation — usually SQL++ or `curl()`. Optimise it rather than raising the ceiling |

## Handler runs but produces wrong results

**Check idempotency.** If a mutation is delivered twice — during rebalance, failover, or redeploy — does the handler still produce the right answer? The second run must overwrite cleanly, not append or double-count.

**Check the Feed Boundary.** A function deployed with **Everything** against an existing collection processes every existing document. If the handler writes derived documents, you will see derived documents generated from historical data. That is the setting working as designed.

**Check for deduplication assumptions.** The KV engine deduplicates rapid successive mutations before they reach DCP, so the handler sees the final state and may never see intermediate states. You cannot distinguish create from update, and you cannot see the previous value. Logic that assumes it observes every transition will be wrong under load.

**Check the Eventing Storage collection.** Functions sharing a storage collection must have distinct `user_prefix` values, or their internal documents collide. Also confirm that nothing — an application, a migration script, another Eventing function — is writing into or flushing that collection.

## Timer not firing

**Was the callback renamed?** Timers store the callback name. If the function code was updated and the callback renamed, timers created before the rename fire and fail to find their callback. Recreate the timers after renaming, or keep the old callback around during the transition. The timer-callback-missing counter in the statistics is the signal.

**Was the function undeployed?** Timers are deleted when the function is deleted **or undeployed**. Pausing does not destroy them. If you undeployed between creating a timer and its fire time, it is gone.

**Was the timer scheduled in the past?** `createTimer` requires the `Date` to be in the future; behaviour is otherwise unspecified. Guard for this before calling.

**Was the reference reused?** Creating a timer with the same reference as an existing one for the same function and callback **implicitly cancels the old timer**. If two code paths share a reference, one silently replaces the other.

**Is the Eventing Storage collection healthy?** Timer state lives there. If the collection is full or the bucket is under memory pressure, timer creation fails. Monitor its usage, and remember roughly 832 bytes plus context size per active timer.

**Did a callback error block the queue?** A runtime or programmatic error in the callback can permanently block timer execution. Check the application log for callback failures.

**Are the cluster clocks synchronised?** Timers require NTP at node startup and periodically thereafter.

## Eventing service memory pressure

The Eventing Service has its own memory quota, configured in the cluster's memory settings separately from the Data Service quota. If it runs short, processing throttles. Common causes:

- Too many workers (`worker_count` × participating Eventing nodes) with a large `timer_context_size`
- Large documents held in memory during handler execution
- A large backlog causing the DCP buffer to grow

Fixes: reduce `worker_count`, reduce `timer_context_size`, restrict the function to fewer nodes with `num_nodes_running` (8.0+), or add Eventing nodes. From 8.0 the Eventing Service can be added to or removed from existing nodes dynamically, with an automatic rebalance.

## Eventing in an XDCR topology

If a function writes to documents in an XDCR-replicated bucket, its writes are mutations that replicate. In a **bidirectional (active-active)** topology that can produce "ping-pong" replication: a write on cluster A replicates to B, triggers the function there, which writes again, and so on. Couchbase's documentation calls this out explicitly as a limitation to design around — add guards so a function does not act on a document it has already processed (a marker field, a version check, or a type filter).

Related: before enabling XDCR Conflict Logging, check that Eventing functions in replicated buckets are not themselves generating excessive conflicts. See `couchbase-xdcr`.
