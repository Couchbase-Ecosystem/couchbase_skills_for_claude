# Workload shapes — sizing by access pattern

Different workload shapes have different sizing characteristics. The same total data size can need very different cluster shapes depending on whether it's read-heavy, write-heavy, vector-search-driven, or time-series-shaped. This reference walks through the common workload shapes and the sizing characteristics of each.

> **This reference is qualitative by design.** It tells you which dimension binds for each shape and where to go for the math; it does not contain multipliers, IOPS specifications or throughput figures, because Couchbase publishes none per workload shape. Do the arithmetic in `memory.md`, `disk.md` and `indexes.md`, then use this file to sanity-check the shape of the answer.

## Contents

- [Read-heavy (>90% reads)](#read-heavy-90-reads)
- [Write-heavy (>50% writes)](#write-heavy-50-writes)
- [Mixed transactional (40-60% reads/writes)](#mixed-transactional-40-60-readswrites)
- [Burst-prone (Black Friday, viral events)](#burst-prone-black-friday-viral-events)
- [Time-series (mostly appends with retention)](#time-series-mostly-appends-with-retention)
- [Vector search workloads](#vector-search-workloads)
- [Multi-tenant SaaS](#multi-tenant-saas)
- [Analytical (OLAP) workloads](#analytical-olap-workloads)
- [Cache-like workload](#cache-like-workload)
- [Summary table](#summary-table)
- [Quick decision tree](#quick-decision-tree)

## Read-heavy (>90% reads)

Examples: content delivery, catalog browsing, user profile lookups.

**Characteristics:**
- Working set can be relatively small if the cold tail is large
- KV reads dominate; very latency-sensitive
- Indexes are read but rarely written

**Sizing priorities:**
1. **RAM** — fit the working set comfortably; this is the binding constraint
2. **Network egress** — many small reads means high response bandwidth. Compute it: `peak_qps × avg_response_size`
3. **CPU for Query** if there's a query-heavy component
4. **More nodes** to distribute read load

**A correction worth making explicitly: replicas do not serve ordinary reads.** An ordinary `get` always goes to the active vBucket. Replica reads are a separate, explicit SDK operation used during failover, and can return stale data. Raising the replica count to "scale reads" costs RAM, disk and replication bandwidth and returns nothing in read throughput. Scale reads by adding **nodes** (which spreads active vBuckets wider) or Query capacity — not replicas.

**Service mix:**
- 3-5 data nodes for low-latency KV
- 2 query/index nodes if query is meaningful
- Eventing usually not needed

**Common mistake:** over-sizing for storage when most of it is cold. Measure the resident ratio on a running cluster rather than assuming full residency — and remember the storage-engine floors (Couchstore quota ≥ 10% of dataset, Magma ≥ 1%) set a lower bound regardless of how cold the tail is.

## Write-heavy (>50% writes)

Examples: event ingestion, IoT telemetry, audit logs.

**Characteristics:**
- High disk write throughput
- Replicas amplify write cost
- Indexes are expensive (every write updates every index)
- Compaction runs constantly

**Sizing priorities:**
1. **Disk IOPS** — the usual binding constraint. Load-test to find the number; there is no documented per-workload IOPS table
2. **CPU for compaction** — it has to keep up with the write rate
3. **Network for replication** — compute it: `write_rate × avg_doc_size × replica_count`
4. **Fewer indexes** — each index is maintained on every write to the collection
5. **Storage engine** — Magma's lower append-only multiplier (2.2× vs Couchstore's 3×) matters most here. **Enterprise Edition only**

**Service mix:**
- 5+ data nodes spread the write load
- Index nodes separate from data (so index updates don't compete with KV writes)
- Eventing if you need to react to writes

**Common mistake:** treating it like a read-heavy workload. Write-heavy clusters need fewer and leaner indexes, more nodes for write parallelism, and IOPS provisioned from a load test rather than a default volume.

## Mixed transactional (40-60% reads/writes)

Examples: e-commerce, SaaS apps, social platforms.

**Characteristics:**
- Most common shape
- Indexes get both heavy reads (queries) and heavy updates (writes)
- Working set is moderate (active users + hot data)

**Sizing priorities:**
- Balanced across RAM, disk, CPU
- More indexes than write-heavy, fewer than read-heavy
- Service separation (data vs query/index) helps with isolation

**Service mix:**
- Pattern B from `nodes.md`: data nodes + query/index nodes
- 3 data + 2 query/index is a typical starter shape

## Burst-prone (Black Friday, viral events)

Examples: e-commerce sale, viral content, sports event traffic.

**Characteristics:**
- 3-10x normal load for hours or days, then back to baseline
- Cluster can't be scaled in real time (rebalances take too long)
- Need to pre-provision for peak

**Sizing priorities:**
1. **Size for peak, not average.** The documented RAM formula already carries a 25% overhead factor and an 85% high-water mark; apply it to *peak* inputs rather than stacking another arbitrary margin on average inputs
2. **CPU and network are usually the binding constraints** at burst
3. **More nodes**, not more replicas — replicas don't serve ordinary reads
4. **Cache layer in front** if the burst is read-dominated and cacheable

**Pre-burst checklist:**
- Validate the cluster handles peak via a real load test — this is the shape where an untested assumption is most expensive
- Confirm auto-failover settings won't trigger spuriously under load
- Confirm no rebalance or compaction window overlaps the burst
- Have a rollback plan if something goes wrong

**Common mistake:** sizing for average. The cluster runs fine for 51 weeks, then collapses on the one week that matters.

## Time-series (mostly appends with retention)

Examples: metrics, IoT, audit logs, event streams.

**Characteristics:**
- Write rate steady or growing, read rate moderate
- Mostly append; rarely updates
- Retention-bounded; data ages out
- Often time-range queries

**Sizing priorities:**
1. **Disk IOPS for sustained writes** — IOPS dominates
2. **Storage** — grows linearly until retention kicks in
3. **Compaction** — works hard against the steady write load
4. **Working set is tiny** (typically just the recent time window)

**Service mix:**
- Data-heavy nodes (lots of disk, moderate RAM)
- **Magma** storage engine — its documented 1% memory-to-data floor (against Couchstore's 10%) and lower disk multiplier are exactly what this shape wants. **Enterprise Edition only**; in Community Edition, Couchstore is the only option and both figures are worse
- **Full ejection**, which is the documented pairing for Magma
- Collection rotation for retention (see the `couchbase-data-modeling` skill's time-series reference)

**Sizing tip:** the steady-state size is bounded by retention. If you write 1 GB/day and keep 90 days, max size is 90 GB. Plan for retention-stable size, not unlimited growth.

## Vector search workloads

Examples: semantic search, RAG, recommendation systems, image similarity.

**Characteristics:**
- Vector indexes dominate RAM (see `indexes.md`)
- Read-heavy on the vector side
- Often combined with scalar filtering (hybrid search)
- Document size larger due to embedding storage

**Sizing priorities:**
1. **Memory for the vector index** — typically the largest single line item in the whole sizing
2. **Large-memory nodes** for whichever service carries the index
3. **Storage for the embeddings themselves** — `docs × dimensions × 4 bytes` for float32 is 6 KB per document at 1536 dimensions, before any index structure
4. **CPU for vector similarity computation**

**Version gate:** Couchbase Server **8.0** introduces Hyperscale vector indexes (a single vector column, documented for billions of documents with a low memory footprint), Composite vector indexes (vector plus scalar columns for filtered search), and Search vector indexes (hybrid vector/text/geospatial). On 7.x, only the Search Service's earlier vector capability is available. Gate the advice on version.

**Service mix:**
- Dedicated large-memory nodes for the service carrying the vector index — the Search Service for Search vector indexes, the Index Service for Hyperscale and Composite indexes
- Separate Data nodes for the source documents
- Query nodes if you're doing hybrid search (vector plus SQL++ scalar filtering)

**Shape of the sizing for 10M documents at 1536 dimensions:** the raw embedding payload alone is `10M × 1536 × 4 ≈ 60 GB` before any index structure. That figure is arithmetic and safe to quote. The *index* size on top of it is not published — build the index on a representative sample and measure it, then size the nodes from the measurement.

**Common mistake:** putting vector indexes on the same nodes as data and under-budgeting memory. Compute the raw payload first; it is usually large enough on its own to settle the service-separation question.

## Multi-tenant SaaS

Examples: B2B SaaS products with many customer tenants.

**Characteristics:**
- Per-tenant access control (scope-per-tenant pattern, see `couchbase-data-modeling`)
- Wildly varying tenant sizes (one tenant 100x bigger than another)
- Queries scoped per-tenant
- Background jobs across all tenants

**Sizing priorities:**
1. **Capacity for the LARGEST tenant** scaled appropriately
2. **Per-tenant working set** sums across tenants
3. **Index per scope** if access patterns differ per tenant
4. **Resource isolation** for any noisy-neighbor concerns

**Service mix:**
- Similar to mixed transactional
- Consider separate clusters for very large tenants versus the long tail of small ones — the tradeoff is additional operational surface against noisy-neighbour isolation

**Sizing math:** sum the per-tenant working sets and feed that total into the documented formula in `memory.md`, then add explicit headroom for the largest tenant's projected growth — sized from that tenant's actual growth rate, not a generic buffer.

Note the **30-bucket-per-cluster maximum**: bucket-per-tenant does not scale past 30 tenants and is expensive well before that (each bucket carries its own quota and a documented 0.2 cores per node). **Scope-per-tenant** is the pattern that scales.

## Analytical (OLAP) workloads

Examples: business intelligence, ad-hoc reporting, data exploration.

**Characteristics:**
- Few, expensive queries (vs many cheap queries)
- Large scans and aggregations
- Latency tolerance is higher (seconds OK)
- Doesn't impact OLTP if isolated

**First: establish which product.** There are two distinct offerings and they size differently:
- The **Analytics Service** running inside a Couchbase Server cluster (documented minimum quota **1024 MB**)
- **Capella Analytics** / **Couchbase Enterprise Analytics** — separate analytics products with their own deployment and sizing model. (The name "Capella Columnar" is retired.)

**Sizing priorities for the in-cluster Analytics Service:**
1. **Storage** — it maintains its own copies of the ingested data
2. **CPU and memory scale with query complexity** — joins and large aggregations far more than scans
3. **Dedicated nodes** so OLAP doesn't disrupt OLTP

**Service mix:**
- Dedicated Analytics node pool (Pattern C from `nodes.md`)
- Size it from a representative workload in staging; Couchbase publishes no per-node RAM guidance for it

## Cache-like workload

Examples: session store, computed-result cache, page cache.

**Characteristics:**
- High write rate (cache populates and evicts constantly)
- High read rate (every cached read is a hit)
- TTL-heavy (entries expire)
- Data loss acceptable (it's a cache; re-compute is possible)

**Sizing priorities:**
1. **RAM** — the entire cache should fit
2. **Replica = 0 or 1** — losing the cache isn't catastrophic
3. **Ephemeral bucket type** — no disk persistence, so no compaction and no disk sizing
4. **Choose the Ephemeral eviction policy deliberately** — see below

**Important correction: Ephemeral buckets do not have `fullEviction` or `valueOnly` policies.** Those are Couchbase-bucket ejection policies. Ephemeral buckets offer two different options ([Memory](https://docs.couchbase.com/server/current/learn/buckets-memory-and-storage/memory.html)):

| Ephemeral policy | Behaviour |
|---|---|
| **No ejection** | Refuses new data once the quota is reached — the bucket starts erroring rather than silently dropping data |
| **Eject when RAM is full** | Evicts using a not-recently-used (NRU) algorithm |

For a cache, "eject when RAM is full" is almost always what you want; "no ejection" turns a full cache into an application error. Pick deliberately.

Two further constraints on Ephemeral buckets: they support only the **`majority`** durability level (the persistence-based levels need disk), and **Memcached buckets were removed in Couchbase Server 8.0**, so Ephemeral is the in-memory bucket type.

**Service mix:**
- Data only, often a single-bucket use case
- Light Query usage if any

## Summary table

| Workload | Replicas | Indexes | Binding constraint | Special |
|---|---|---|---|---|
| Read-heavy | 1 (2 if durable writes must survive a failure) | Many (covering) | RAM, then egress | Scale reads with nodes, **not** replicas |
| Write-heavy | 1 | Few | Disk IOPS | Separate Index nodes; Magma (EE) |
| Mixed | 1 | Moderate | RAM | Data + Query/Index split |
| Burst | 1 | As needed | CPU and network at peak | Size the formula against peak inputs; load-test |
| Time-series | 1 | Minimal | Disk capacity | Magma (EE) + full ejection + collection rotation |
| Vector | 1 | Vector indexes (8.0+) | Memory for the vector index | Dedicated large-memory nodes; compute the raw payload first |
| Multi-tenant | 1 | Per-tenant | Sum of tenant working sets | Scope-per-tenant; 30-bucket cluster max |
| Analytics | n/a | n/a | Storage, then query memory | Establish which Analytics product first |
| Cache | 0-1 | None | RAM | Ephemeral bucket, NRU eviction, `majority` durability only |

## Quick decision tree

- **Workload is mostly reads?** → larger working set, more indexes, **more nodes** — replicas do not serve ordinary reads
- **Workload is mostly writes?** → load-test for IOPS, fewer indexes, separate Index nodes, Magma if you're on Enterprise Edition
- **Burst-prone?** → apply the documented RAM formula to *peak* inputs, then load-test at peak
- **Time-series?** → collection rotation, Magma + full ejection (EE), small working set, disk-heavy nodes
- **Vector search?** → 8.0+ for Hyperscale/Composite indexes; compute the raw embedding payload, then measure the real index; dedicated large-memory nodes
- **Multi-tenant?** → scope-per-tenant, not bucket-per-tenant (30-bucket cluster maximum); size for the sum plus largest-tenant growth
- **Analytics?** → which product? In-cluster Analytics Service, or Capella Analytics / Couchbase Enterprise Analytics. Dedicated nodes either way
- **Cache?** → Ephemeral bucket with NRU eviction (**not** `fullEviction` — that's a Couchbase-bucket policy), replica=0 if loss is tolerable, `majority` is the only durability level available
