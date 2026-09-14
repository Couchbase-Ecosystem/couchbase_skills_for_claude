# Performance patterns

How to write client code that pushes throughput, minimizes latency, and uses the SDK's primitives well. The biggest wins come from a few patterns; everything else is incremental.

> **Verify SDK symbols against your pinned SDK version.** The Python and Java symbols shown here reflect the current documented surface. Method names and option classes differ per SDK and per major version — confirm before use.
>
> **No performance numbers are quoted in this reference on purpose.** Throughput and latency depend entirely on your hardware, document sizes, network and cluster shape. Measure on your own cluster; don't carry a published multiplier into a sizing or design decision.

## Contents

- [The top 3 wins](#the-top-3-wins)
- [Async patterns](#async-patterns)
- [Bulk operations](#bulk-operations)
- [Subdocument ops — the underused win](#subdocument-ops--the-underused-win)
- [Connection settings for throughput](#connection-settings-for-throughput)
- [Latency optimization](#latency-optimization)
- [Throughput optimization](#throughput-optimization)
- [Caching considerations](#caching-considerations)
- [Profiling](#profiling)
- [Anti-patterns](#anti-patterns)
- [Quick decision tree](#quick-decision-tree)

## The top 3 wins

1. **Async over sync** for any high-concurrency workload — frees the calling thread to do other work while waiting on cluster I/O
2. **Bulk ops over loops** — one pipelined multi-operation, or bounded concurrent operations, instead of N sequential round-trips
3. **Subdocument ops over full-doc reads/writes** — `lookup_in` and `mutate_in` move only the fields you need

If you do nothing else, do these three. Most performance complaints trace back to violating one of them.

## Async patterns

### When async wins

- Web servers handling many concurrent requests — each request does a few KV ops; threading per request wastes resources
- Pipelines that fan out many independent reads/writes
- Background workers processing parallel streams of data

### When async is overhead

- Batch scripts doing sequential work — sync is simpler and equivalent in throughput
- CLI tools — startup cost of an async runtime isn't worth it
- Simple ETL with no parallelism

### Async example — Python asyncio

```python
# Python SDK 4.x asyncio variant
import asyncio
from acouchbase.cluster import AsyncCluster
from couchbase.options import QueryOptions

async def fetch_user_with_orders(cluster, user_id):
    bucket = cluster.bucket("app_data")
    users = bucket.scope("_default").collection("users")
    orders = bucket.scope("_default").collection("orders")

    # Fetch user and their orders in parallel
    user_task = asyncio.create_task(users.get(f"user::{user_id}"))
    # Always parameterize — never interpolate a value into SQL++
    orders_task = asyncio.create_task(
        cluster.query("SELECT o.* FROM `app`.`_default`.`orders` o WHERE o.user_id = $uid",
                      QueryOptions(named_parameters={"uid": user_id}))
    )

    user_result = await user_task
    orders_result = await orders_task

    return {
        "user": user_result.content_as[dict],
        "orders": [row async for row in orders_result.rows()]
    }
```

The two operations run concurrently; total latency = max(user_latency, orders_latency), not sum.

### Async example — Java reactive

```java
// Java SDK 3.x reactive API (Project Reactor)
Mono<JsonObject> userMono = collection.reactive().get("user::" + userId)
    .map(result -> result.contentAsObject());

Flux<JsonObject> ordersFlux = cluster.reactive()
    .query("SELECT o.* FROM `app`.`_default`.`orders` o WHERE o.user_id = $1",
           QueryOptions.queryOptions().parameters(JsonArray.from(userId)))
    .flatMapMany(ReactiveQueryResult::rowsAsObject);

return Mono.zip(userMono, ordersFlux.collectList())
    .map(tuple -> /* combine */);
```

Same pattern — two operations run concurrently via Reactor.

## Bulk operations

### KV multi-get

```python
# Slow — sequential, one round-trip per key
for user_id in user_ids:
    user = collection.get(f"user::{user_id}")

# Faster — one pipelined multi-operation
results = collection.get_multi([f"user::{uid}" for uid in user_ids])
```

The Python SDK documents `get_multi`, `upsert_multi`, `insert_multi` and `remove_multi` for this, with the caveat that these are marked a **volatile API** that may change — pin your SDK version and re-check on upgrade ([Bulk operations guide](https://docs.couchbase.com/server/current/guides/bulk-operations.html)).

**Most SDKs express bulk work through the language's own concurrency primitive rather than a `*_multi` helper**, and the bulk-operations guide shows exactly that:

| SDK | Documented bulk pattern |
|---|---|
| Python (blocking) | `get_multi` / `upsert_multi` / `insert_multi` / `remove_multi` (volatile API) |
| Java | `Flux.fromIterable(...)` over the reactive collection (Project Reactor) |
| Node.js | `Promise.all()` over the collection's async methods |
| .NET | `List<Task<IMutationResult>>` + `Task.WhenAll()` |
| Go | goroutines with a `WaitGroup` or errgroup |

Whichever form you use, **bound the concurrency** — see the semaphore pattern below.

### Bulk insert / upsert

```python
# Slow — sequential
for doc in documents:
    collection.upsert(doc["id"], doc)

# Fast — concurrent
import asyncio
async def bulk_upsert(collection, documents, concurrency=50):
    semaphore = asyncio.Semaphore(concurrency)
    async def upsert_one(doc):
        async with semaphore:
            await collection.upsert(doc["id"], doc)
    await asyncio.gather(*[upsert_one(d) for d in documents])
```

The semaphore caps parallelism so you don't overwhelm the cluster. The right value depends on your cluster size, document size and network — start conservative and raise it while watching cluster CPU and the client's error rate. There is no universal number.

For very large loads (millions of docs), use the dedicated `cbimport` tool rather than client code — it handles batching, retries, and progress reporting.

### Bulk patterns for queries

Queries can't be "bulked" — each query is its own request. But:

- Use parameterized queries — the same statement text with different bound values lets the cluster reuse the prepared plan, and it is the only safe way to handle external input
- Reference collections fully (`` `bucket`.`scope`.`collection` ``), or issue the query from a `Scope` object, so it routes correctly
- Avoid `SELECT *` if you only need a few fields

```python
# Same statement text every call — plan is reusable
stmt = ("SELECT u.name, u.email FROM `app`.`_default`.`users` u "
        "WHERE u.tier = $tier")
for tier in tiers:
    result = cluster.query(stmt, QueryOptions(named_parameters={"tier": tier}))
```

Named parameters (`$tier` + `named_parameters={...}`) and positional parameters (`$1` + `positional_parameters=[...]`) are both documented and both safe; named is preferred once there is more than one ([SQL++ from the Python SDK](https://docs.couchbase.com/python-sdk/current/howtos/n1ql-queries-with-sdk.html)).

## Subdocument ops — the underused win

When you only need one or two fields of a large document, `lookup_in` and `mutate_in` move only those fields over the wire.

```python
# Python SDK 4.x
import couchbase.subdocument as SD

# Slow — fetches the full document just to read 'email'
user = collection.get("user::42").content_as[dict]
email = user["email"]

# Fetches only the email field
result = collection.lookup_in("user::42", [SD.get("email")])
email = result.content_as[str](0)
```

The saving scales with how much of the document you are *not* transferring, so it matters most on large documents and hot paths. Measure rather than assuming a threshold.

`mutate_in` for updates is similarly valuable — modifying one field of a large document without it means reading and rewriting the whole thing.

```python
collection.mutate_in("user::42", [SD.upsert("last_login", now)])
```

Documented sub-document operations include `SD.get`, `SD.exists`, `SD.upsert`, `SD.insert`, `SD.replace`, `SD.remove`, `SD.array_append`, `SD.array_prepend` and `SD.counter`.

**Documented limits** — worth knowing before designing around sub-document ops:

| Limit | Value |
|---|---|
| Operations per `lookup_in` / `mutate_in` request | 16 |
| Sub-document path length | 1024 bytes |
| Sub-document path nesting level | 32 |

Sources: [Python sub-document operations](https://docs.couchbase.com/python-sdk/current/howtos/subdocument-operations.html), [Size Limits](https://docs.couchbase.com/server/current/learn/clusters-and-availability/size-limitations.html).

## Connection settings for throughput

The Java SDK's documented default is **one** KV connection per node (`numKvConnections` = 1) and 12 HTTP connections (`maxHttpConnections`). For very high-throughput workloads you can raise these:

```java
// Java SDK 3.x
Cluster cluster = Cluster.connect(connStr,
    ClusterOptions.clusterOptions(username, password)
        .environment(env -> env.ioConfig(io -> io.numKvConnections(4))));
```

Other SDKs expose equivalent settings under their own names — look them up in that SDK's client-settings page rather than porting the Java spelling.

Only tune if you've profiled and seen connection contention. Most apps don't need this.

## Latency optimization

For latency-critical paths (request handlers needing sub-10ms p99):

1. **KV reads only** — a KV `get` by key is a direct hash lookup with no index and no query engine; a SQL++ query for the same document is strictly more work
2. **`get` on the active copy only** — don't use the get-all-replicas / get-any-replica operations on the hot path; replicas do not serve ordinary reads and replica data may be stale
3. **Subdocument ops** if only specific fields are needed
4. **Wait-until-ready at startup** so the first request doesn't pay bootstrap cost
5. **Lower operation timeouts** so the SDK doesn't spend long retrying — fail fast and let the request handler decide what to do

## Throughput optimization

For batch/ingest paths needing high total ops/sec:

1. **Async + parallelism** — many concurrent ops, bounded
2. **Bulk ops** where available
3. **No durability requirement** if data loss is acceptable
4. **Reuse connections** — one Cluster for the entire batch job
5. **Batch sized to memory** — async with no limit can run out of memory; semaphore-cap to a reasonable parallelism

For multi-million document ingestion, also consider:
- `cbimport` for one-shot loads (better than client code)
- Eventing functions for transform-during-write
- Multi-node ingestion (each worker writes to its assigned partition)

## Caching considerations

Couchbase serves KV reads from memory, so adding another cache layer in front of it (Redis, application memory) is often unnecessary. Before adding one, **measure your own KV read latency** and compare it against an in-process lookup. Published latency figures are not a substitute for that measurement, and the gap is only worth the added complexity and staleness risk if your measured KV latency is actually the bottleneck.

When caching DOES make sense:
- Cross-request shared data accessed many times per request — cache in-memory per worker
- Heavy aggregation results — cache the aggregated form, not raw data
- Cross-region or constrained network paths where the round-trip itself dominates

Often the right answer is: just hit Couchbase. The simplicity wins.

## Profiling

When something is slow:

1. **Use SDK tracing and metrics** — the SDKs carry built-in threshold-logging and orphaned-response reporting, and support OpenTelemetry integration. Turn these on before guessing
2. **Check the cluster** — look at query and KV statistics server-side; the `couchbase-mcp` skill covers the tooling for that
3. **Time things** — put timing around the suspected slow op, log p50/p95/p99
4. **`EXPLAIN` the query** — for slow SQL++, get the plan. Couchbase Server 8.0 also adds an Automatic Workload Repository (AWR) for query performance statistics and trend analysis

Don't optimize without measurement. The intuitions about "this is probably slow" are often wrong.

## Anti-patterns

- **N+1 query pattern** — fetching a list of IDs, then KV-getting each one in a loop. Use a multi-op or bounded concurrency instead
- **Creating Cluster per request** — see `connection-management.md`
- **Full document reads when subdoc would do** — wastes bandwidth and memory
- **Sync ops in async handlers** — blocks the event loop, kills throughput
- **No connection reuse** — every request paying connection-setup cost
- **Optimistic concurrency loops without backoff** — under contention, busy-loop hammers the cluster

## Quick decision tree

- **High concurrency / web handler?** → async SDK + per-op timeouts + connection pooling
- **Batch / ETL?** → sync SDK or async with bounded parallelism (semaphore)
- **Reading many docs by ID?** → your SDK's multi-op, or bounded concurrent gets
- **Reading specific fields of a doc?** → `lookup_in` (max 16 ops per request)
- **Updating specific fields of a doc?** → `mutate_in` (max 16 ops per request)
- **Counter increment under contention?** → binary collection `increment`, or a sub-document `counter` op — not a CAS loop
- **Throughput too low?** → async, bulk, bounded parallelism. In that order
- **Latency too high?** → KV only (not queries), active copy only, lower timeouts
- **Adding cache layer?** → measure your actual KV latency first; Couchbase is often fast enough that a cache adds complexity and staleness without value
