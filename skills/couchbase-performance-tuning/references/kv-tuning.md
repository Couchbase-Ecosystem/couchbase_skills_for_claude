# KV tuning

## Contents

- [Understanding KV latency sources](#understanding-kv-latency-sources)
- [Working set, watermarks, and ejection](#working-set-watermarks-and-ejection)
- [KV thread pools](#kv-thread-pools)
- [DCP performance](#dcp-performance-replication-xdcr-eventing-analytics)
- [Subdocument vs full document](#subdocument-vs-full-document)
- [Durability and write latency](#durability-and-write-latency)
- [Bulk operations](#bulk-operations)

## Understanding KV latency sources

KV operation latency has three layers:

```
Client -> Network -> Data Service -> Storage
                          |
                    [Memory lookup]    <- fast
                          or
                    [Disk read]        <- much slower
```

The dominant factor in KV latency is whether the document is resident in memory or requires a disk fetch. Everything else is secondary. Establish your own baseline latency percentiles on your hardware and workload — published per-operation latency figures do not transfer between deployments, storage engines, or instance types.

## Working set, watermarks, and ejection

Couchbase ejects documents from memory when bucket memory use crosses the high watermark, and continues until it falls back to the low watermark.

Documented defaults:
- `memoryLowWatermark`: **75%**
- `memoryHighWatermark`: **85%**

Once ejection starts, reads of ejected documents require a disk fetch and `ep_bg_fetched` increments.

Ejection policies for Couchbase buckets:

- **Value-only** (the default policy for Couchbase buckets): "The Data Service only ejects a document's data when it ejects it from memory. It keeps the document's keys and metadata in memory." Favors performance over memory efficiency.
- **Full ejection**: "The Data Service removes the entire document, including its metadata and keys, when it ejects a document from memory." Lower memory overhead; key operations may also need a disk fetch. The docs specifically recommend full ejection for buckets using the Magma storage engine with low memory-to-data ratios.

The ejection policy is set at bucket creation and can be changed later via the REST API, CLI, or Web Console.

**How to read cache miss rate:** there is no published universal target. Track the metric over time on your own cluster and treat a rising trend, or a step change after a deployment, as the signal. If misses are climbing, the working set has outgrown the memory quota — add RAM, add nodes, reduce the working set, or move the bucket to Magma with full ejection.

> **8.0 metric rename:** the "Cache Miss Ratio" metric was renamed "Get Miss Ratio" in 8.0. Update dashboards and alert rules that reference the old name.

Sources: https://docs.couchbase.com/server/current/learn/buckets-memory-and-storage/memory.html and https://docs.couchbase.com/server/current/release-notes/relnotes.html

## KV thread pools

The KV engine's reader and writer thread pools are the ones that matter most for storage-bound workloads:

- **Reader threads** (`num_reader_threads`) — fetch items from disk for background fetches
- **Writer threads** (`num_writer_threads`) — flush mutations to disk

**These are cluster-wide settings, not per-bucket settings.** They are configured through the thread-allocation REST endpoint (`/settings/...`), which applies "across the entire cluster."

Three ways to set each:

1. Let Couchbase choose a default value automatically
2. Choose the value that optimizes disk I/O
3. Set the number of threads per node manually, to a value **between 1 and 64**

The docs' own caution: "Using a higher number of threads may improve performance if your hardware supports it, such as when your CPU has a larger [number] of cores," but "setting the number of threads higher than your hardware supports can reduce performance."

When to consider raising reader threads: `ep_bg_fetched` is high while disk utilization is still below saturation, so more concurrent reads can actually be served.

When to consider raising writer threads: `ep_diskqueue_drain` consistently lags `ep_diskqueue_fill` while disk write throughput is still below the device's capability.

In both cases, change one pool at a time and measure. Do not exceed what the storage subsystem can do in parallel — NVMe handles high queue depth, spinning disks do not.

Sources: https://docs.couchbase.com/server/current/rest-api/rest-reader-writer-thread-config.html and https://docs.couchbase.com/server/current/learn/buckets-memory-and-storage/storage-settings.html

## DCP performance (replication, XDCR, Eventing, Analytics)

DCP (Database Change Protocol) is the internal feed behind intra-cluster replica replication, XDCR, the Analytics Service, Eventing, and the Search Service. DCP streams are backpressure-aware: a slow consumer causes the stream to back up rather than overwhelming the consumer.

Signs of DCP pressure:
- `ep_dcp_replica_items_remaining` greater than zero and growing (internal replicas falling behind)
- XDCR `changes_left` growing
- Analytics ingestion showing pending operations
- Eventing backlog growing

Root causes and fixes:

| Symptom | Likely cause | Fix |
|---|---|---|
| All DCP consumers behind immediately after a rebalance | Rebalance generates a burst of mutations | Usually normal — confirm it drains rather than plateaus |
| XDCR behind, disk I/O high | Disk saturated by XDCR reads competing with the workload | Throttle XDCR bandwidth on the replication; review storage capability |
| Eventing backlog growing with no rebalance running | Handler execution too slow | Raise worker count; optimize the handler |
| Analytics behind | Analytics nodes under-resourced | Add Analytics nodes or raise the Analytics memory quota |
| One vBucket's replica consistently behind | Node-local disk or CPU problem | Check that node in isolation before tuning cluster-wide |

Backpressure is a symptom reporter, not the fault. Find the slow consumer or the saturated device before changing DCP-related settings.

## Subdocument vs full document

For updates that touch a small number of fields in a larger document, subdocument operations (`mutate_in` / `lookup_in`) do less work than a full `replace`:

- Full `replace`: the client reads the whole document, modifies it, and sends the whole document back
- `mutate_in`: the server applies the field-level change; the full document body does not cross the network in either direction

The benefit scales with how large the document is relative to the fields being changed — it is largest for big documents with small edits, and negligible for small documents. Measure on your own payload sizes rather than assuming a multiplier.

Subdocument path limits are documented: path length up to 1024 bytes, nesting up to 32 levels.

See `couchbase-app-integration/references/performance-patterns.md` for SDK code.

Source: https://docs.couchbase.com/server/current/learn/clusters-and-availability/size-limitations.html

## Durability and write latency

Durable writes "typically take longer to complete than regular writes because they require additional replication or persistence steps." The server-side durability levels are:

| Level | Guarantee |
|---|---|
| (no durability requirement) | The default for a normal KV write — acknowledged from the active node's memory. Not a durable write. |
| `majority` | "A majority of Data Service nodes must store the mutation to memory for the write to be durable." |
| `majorityAndPersistActive` | "A majority of Data Service nodes must store the mutation in-memory. Also, the node that hosts the active vBucket must write and synchronize the mutation to disk." |
| `persistToMajority` | "A majority of Data Service nodes must save and synchronize the mutation to disk." |

**Durability is opt-in per operation.** A write with no durability level specified is not a durable write — `majority` is not applied automatically.

Cost ordering is predictable — each level adds either replication round-trips or disk synchronization on top of the one above it — but the actual latency added depends entirely on replica count, network round-trip time, and storage fsync latency. Benchmark the levels on your own cluster before committing to one.

Guidance: apply the weakest level that satisfies the durability requirement of that specific operation, rather than setting one level globally. Reserve `persistToMajority` for writes where loss is genuinely unacceptable.

Note the SDK-level durability timeout default is 10 seconds; a durable write that cannot be satisfied fails rather than hanging indefinitely.

Source: https://docs.couchbase.com/server/current/learn/data/durability.html

## Bulk operations

Single-document operations carry per-operation overhead (round-trip, per-request processing). For bulk workloads:

- **Batch reads** — most SDKs expose a multi-get or batched-lookup pattern. Batch size should be tuned against your own latency and memory behavior; there is no universal optimal batch size.
- **Async / reactive APIs** — pipeline operations without waiting for each acknowledgement. This is usually the single largest throughput gain available on the client side.
- **Do not serialize writes** — send N operations, then collect N responses, rather than round-tripping each one. Most SDKs do this automatically in async mode.

Relevant hard limits when sizing batches: max document (value) size is 20 MB, max key length is 250 bytes, max concurrent key-value connections is 60,000 per Data node across ports 11207 and 11210.

**On throughput targets:** achievable KV operations per second per node depends on document size, ratio of reads to writes, durability level, residency, storage engine, CPU, and network. Do not plan against a quoted ops/sec figure from any source, including this one. Load-test the actual workload shape on the actual instance type, then size from that measurement. If throughput plateaus while latency stays flat, look for a client-side or connection-count limit; if latency climbs with throughput, the server or storage is the constraint.

Source: https://docs.couchbase.com/server/current/learn/clusters-and-availability/size-limitations.html
