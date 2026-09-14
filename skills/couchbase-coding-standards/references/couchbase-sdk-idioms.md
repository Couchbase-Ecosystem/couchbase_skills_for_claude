# Couchbase SDK idioms

How to use the SDK the way it's meant to be used. Covers connection lifecycle, the KV-vs-query decision, batching, async, and per-language grain.

> **Verify before you assert.** The symbols below reflect the current 3.x/4.x SDK generation and are drawn from the SDKs' own documentation, but method names, option objects, and import paths differ across SDKs, across major versions, and over time. Always check the project's pinned SDK version — first against existing usage in the codebase, then the versioned SDK docs at `https://docs.couchbase.com/<sdk>/current/` — before writing or approving a symbol. If it can't be verified against the pinned version, flag the line rather than guessing.

## Contents

- [Connection lifecycle](#connection-lifecycle)
- [The object hierarchy](#the-object-hierarchy)
- [KV vs query](#kv-vs-query--choose-kv-when-you-can)
- [Batching](#batching)
- [Timeouts and options](#timeouts-and-options)
- [Async and blocking](#async-and-blocking)
- [Per-language grain](#per-language-grain)
- [Anti-patterns](#anti-patterns)
- [Checklist](#checklist)

## Connection lifecycle

**Connect once, reuse for the process lifetime.** The `Cluster` object is expensive to create (it bootstraps topology, opens sockets, negotiates auth). Create it at startup, hold it, share it. Never open a cluster (or bucket, or collection) per request or per operation — that's the single most common performance defect in Couchbase application code.

```python
# GOOD — module/app-level singleton, created once
from couchbase.cluster import Cluster
from couchbase.auth import PasswordAuthenticator
from couchbase.options import ClusterOptions

cluster = Cluster.connect(
    conn_str,                                   # from env/secrets, never a literal
    ClusterOptions(PasswordAuthenticator(user, password)),
)
bucket = cluster.bucket("app_data")
collection = bucket.scope("profiles").collection("users")
# reuse `collection` for the life of the process
```

- **Don't reconnect to recover from a transient error.** Reconnecting is heavy and usually wrong; the SDK handles topology changes internally. Retry the operation (see `error-handling-and-resilience.md`), don't rebuild the cluster.
- **Close on shutdown, not between operations.** Tie `cluster.close()` to application shutdown.
- **One cluster object per target cluster.** If the app talks to two clusters, that's two long-lived cluster objects — not one that's re-pointed.

## The object hierarchy

Since SDK 3.x the hierarchy is explicit and KV operations live on the **collection**, not the bucket:

```
Cluster → Bucket → Scope → Collection → (KV ops: get/upsert/insert/replace/remove/lookup_in/mutate_in)
Cluster → query()   (cluster-level SQL++)
Scope   → query()   (scope-level SQL++)
```

Scopes and collections are available in **Couchbase Server 7.0 and later**. The `_default` scope and `_default` collection exist on every bucket, so 7.x-and-later code can still address a bucket as if it were flat — but new code should name its scope and collection explicitly.

- **KV ops are collection-scoped.** `collection.get(key)`, not `bucket.get(key)` (the latter is a pre-3.x idiom and is gone). Reviewers should treat bucket-level KV as a version smell.
- **Name the objects for what they are.** `users_collection`, not `c`. A reader three functions away shouldn't have to trace what `c` points at.

## KV vs query — choose KV when you can

The most important idiom in Couchbase code: **if you have the document key, use a KV operation, not SQL++.** A KV `get` by key is a direct hash lookup — sub-millisecond, no index, no query engine. A `SELECT ... WHERE META().id = $k` for the same thing is far more expensive and adds an index dependency.

| You want | Use | Not |
|---|---|---|
| One document by known key | `collection.get(key)` | `SELECT ... WHERE META().id = ...` |
| Write/replace a known document | `collection.upsert/replace(key, doc)` | `UPDATE ... WHERE META().id = ...` |
| Change part of a large doc | `collection.mutate_in(key, [...])` (subdoc) | read-modify-write of the whole doc |
| Find docs by a non-key field | SQL++ query (parameterized) | scanning KV |
| Aggregations, joins, ad-hoc filters | SQL++ query | application-side loops over KV |
| Atomic counter | `collection.binary().increment(...)`, or a sub-document `counter` op | a CAS read-modify-write loop |

Reaching for SQL++ when a KV op would do is a review finding, not a preference.

**Sub-document limits to know before designing around them** ([Size Limits](https://docs.couchbase.com/server/current/learn/clusters-and-availability/size-limitations.html)): at most **16 operations** per `lookup_in`/`mutate_in` request, sub-document path length **1024 bytes**, path nesting level **32**. Document key maximum is **250 bytes**; document value maximum is **20 MB**.

## Batching

For many independent KV operations, batch — don't loop one-at-a-time and await each. Batching pipelines the requests and cuts round-trips.

- **Python (blocking):** the documented multi-operations are `get_multi`, `upsert_multi`, `insert_multi` and `remove_multi`. Couchbase's bulk-operations guide flags these as a **volatile API** that may change — pin the SDK version and re-check on upgrade.
- **Other SDKs express bulk work through the language's own concurrency primitive**, and that is what the bulk-operations guide shows: `Flux.fromIterable(...)` over the reactive collection in Java, `Promise.all(...)` in Node, `List<Task<IMutationResult>>` + `Task.WhenAll()` in .NET, goroutines with a `WaitGroup` in Go. Don't look for a `*_multi` helper that isn't there.
- **Bound the concurrency.** Don't fire 100k concurrent upserts — chunk into batches so you don't exhaust sockets or memory. The right batch size depends on document size, cluster shape and network; start conservative and tune against measured cluster load, rather than copying a number.

Reference: [Bulk operations guide](https://docs.couchbase.com/server/current/guides/bulk-operations.html).

## Timeouts and options

- **Pass options objects, don't rely on implicit defaults for anything that matters.** `GetOptions`, `UpsertOptions`, `QueryOptions` carry timeout, durability, scan consistency, parameters. Making them explicit documents intent.
- **Set timeouts deliberately, with a justification.** A magic `timeout=2500` is a smell; `UpsertOptions(timeout=timedelta(milliseconds=2500))  # 500x p99 KV latency` is a decision.
- **Durability is a per-write choice, not a global default.** In the Python SDK this is `UpsertOptions(durability=ServerDurability(Durability.MAJORITY))`; other SDKs spell the enum differently, so look it up. Use `majority` or stronger only where the write must survive failover; it costs latency, and it has its own longer timeout (Java `kvDurableTimeout` defaults to 10s vs 2.5s for plain KV). Most writes don't need it. Note the persistence-based levels (`majorityAndPersistActive`, `persistToMajority`) apply to Couchbase buckets only — Ephemeral buckets support `majority` at most. See `error-handling-and-resilience.md`.

## Async and blocking

- **Don't mix them.** Pick the blocking API or the async API for a given code path and stay in it. Calling a blocking SDK method inside an async event loop stalls the loop; that's a defect, not a style nit.
- **In async code, never block the loop.** No synchronous sleeps, no blocking I/O, no `.result()`-style waits on the hot path.
- **Match the app's concurrency model.** A FastAPI/asyncio service uses `acouchbase`; a threaded service uses the blocking `couchbase` API. Choosing the wrong one forces awkward bridging code.

## Per-language grain

Follow each SDK's native idiom rather than porting one dialect across all of them:

- **Python** — type hints, `timedelta` for durations; `Cluster.connect(...)` rather than the bare constructor; `acouchbase` for asyncio, `txcouchbase` for Twisted.
- **Java** — reactive (`Mono`/`Flux`) or `CompletableFuture` for async; blocking API returns directly. Don't `.block()` inside a reactive chain.
- **Node/TS** — `async`/`await` over raw promises; `Promise.all` for batching.
- **Go** — explicit `err` returns checked immediately; no ignored errors (`_`), no panics for control flow.
- **.NET** — `async`/`await` with `Task`; `IAsyncEnumerable` for streaming query rows.

Code that reads like it was written for a different language's SDK is a maintainability finding.

## Anti-patterns

- **Connecting per request.** Covered above — the biggest one.
- **KV work done as SQL++** when the key is known.
- **Reading a whole document to change one field** instead of subdocument `mutate_in`.
- **Ignoring the result.** `upsert` returns a mutation result carrying the CAS (and, when mutation tokens are enabled, a token you can use for `consistent_with` query consistency); `get` returns a result whose content must be extracted (`content_as[dict]` in Python, `contentAs(...)` in Java). Silently discarding results hides the CAS, the mutation token, and the success/failure signal.
- **Swallowing SDK exceptions** to "keep going." See `error-handling-and-resilience.md`.
- **String-built SQL++** from user input. See `sqlpp-in-code.md`.

## Checklist

- [ ] Cluster/bucket/collection created once at startup, reused — not per operation
- [ ] KV ops on the collection, not the bucket
- [ ] KV chosen over SQL++ wherever the key is known
- [ ] Subdocument used for partial updates of large documents
- [ ] Many operations batched (multi-ops or gathered async), concurrency bounded
- [ ] Options objects explicit; timeouts justified; durability chosen per-write
- [ ] Blocking vs async not mixed; loop never blocked in async paths
- [ ] Code follows the SDK's native language grain
- [ ] Sub-document requests stay within 16 operations; keys within 250 bytes; documents within 20 MB
- [ ] Version-gated features stated explicitly (7.0+ / 8.0+ / Enterprise Edition only)
- [ ] SDK symbols verified against the project's pinned SDK version — none asserted from memory
