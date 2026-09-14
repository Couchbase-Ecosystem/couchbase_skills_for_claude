---
name: couchbase-sizing
description: "Size Couchbase clusters, plan capacity, and pick the right Capella tier. Use whenever the user asks about sizing, capacity planning, RAM quota, working set, replicas, node count, scale up vs scale out, how much memory / disk / network is needed, Capella tier selection, GSI / FTS / vector index memory, eventing memory budget, or 'will this fit.' Triggers on numerical planning questions distinct from the couchbase-mcp skill (which operates an existing cluster) and the couchbase-data-modeling skill (which designs document shape). Use proactively for: planning a new deployment, deciding whether to scale up or out, right-sizing a Capella tier, estimating storage growth, planning for burst load, sizing for vector search, calculating XDCR bandwidth, deciding replica count, planning multi-service node mix, estimating eventing memory footprint, and any question that starts with 'how much' or 'how many nodes.'"
license: Apache-2.0
---

# Couchbase sizing & capacity planning

A skill for *numerical* planning of Couchbase deployments. Companion to `couchbase-mcp` (which operates clusters) and `couchbase-data-modeling` (which designs the data shape) — this skill answers "how much" and "how many."

## When this skill applies

Use this skill whenever the conversation involves estimating resources or capacity:

- "How much RAM do I need?"
- "How many nodes for X documents?"
- "Which Capella tier should I use?"
- "Will this fit in 32 GB?"
- "Should I scale up or scale out?"
- "How big will the index be?"
- "What replica count?"
- "Sizing for vector search"
- "How much XDCR bandwidth"
- "Capacity for next year's growth"

If the conversation is about *what* to store (modeling), use `couchbase-data-modeling`. If it's about *how to* operate (calling tools), use `couchbase-mcp`. This skill is purely about resource math.

## Pick the right reference

| Question | Read |
|---|---|
| "How much RAM / what's the working set?" | `references/memory.md` |
| "How many nodes? What replica count?" | `references/nodes.md` |
| "How much disk / storage?" | `references/disk.md` |
| "Network bandwidth, XDCR throughput?" | `references/network.md` |
| "How big will the GSI / FTS / vector index be?" | `references/indexes.md` |
| "Which Capella tier?" | `references/capella.md` |
| "Read-heavy vs write-heavy vs vector vs time-series sizing?" | `references/workload-shapes.md` |

## What you need from the user before sizing anything

Sizing math depends on workload data. Without these inputs, the best you can do is order-of-magnitude estimates with explicit assumptions. **Ask the user for any of these that aren't already in context:**

1. **Document count** at present, and expected growth rate (per month or year)
2. **Average document size** (and if it varies a lot, the 95th percentile too)
3. **Reads per second** (peak, not average — sizing is for peak)
4. **Writes per second** (peak)
5. **Working set assumption**: what fraction of documents are "hot" (accessed regularly)? Common: 20%, 50%, 100%
6. **Replica count target** (usually 1 or 2)
7. **Services needed** (Data, Query, Index, Search, Eventing, Analytics, Backup)
8. **TTL / retention** (does data age out?)

If the user doesn't have these numbers, give them a way to estimate. Most users underestimate document count and document size.

## The core sizing equation — use the documented one

Couchbase publishes a Data-service RAM formula in [Sizing Guidelines](https://docs.couchbase.com/server/current/install/sizing-general.html). **Use it rather than inventing one:**

```
cluster_RAM_quota = (total_metadata + working_set) × (1 + overhead_percentage) / high_water_mark

  total_metadata = documents_num × (metadata_per_document + ID_size) × no_of_copies
  working_set    = total_dataset × working_set_percentage
```

Documented constants:

| Constant | Documented value |
|---|---|
| `metadata_per_document` | 56 bytes |
| `high_water_mark` | 85% |
| `overhead_percentage` | 25% |
| `no_of_copies` | `1 + replica_count` |

Two things people routinely get wrong: the metadata term includes the **document ID size**, not just the flat 56 bytes, and the result is a **cluster-wide** quota — divide by node count at the end, don't build node count into the formula.

Couchbase also documents **0.2 CPU cores per bucket per node** for operational stability, and recommends allocating **no more than 90% of a node's memory** to Couchbase services (80% on nodes with little total memory).

`memory.md` walks through this with worked examples.

## Three rules of thumb — and they are estimates

The formula above is documented; the three rules below are **field heuristics, not documented values.** Label them as such when you use them, and replace each with a measurement as soon as the user has one.

**Rule 1 — Working set is what matters, not total data size.** *(estimate)*
Couchbase keeps the working set in RAM; cold data lives on disk and pages in on demand. Sizing for 100% residency when the real working set is a fraction of the data over-provisions substantially. The documented ratios that *are* authoritative are the storage-engine minimums: a Couchstore bucket's memory quota should be at least **10%** of the expected dataset size, a Magma bucket's at least **1%** ([Memory](https://docs.couchbase.com/server/current/learn/buckets-memory-and-storage/memory.html)).

**Rule 2 — Always plan for one node failure.** *(estimate)*
With replica count = 1, losing one node means the cluster absorbs that node's load on the remaining nodes. Size so the post-failure cluster still has headroom. `nodes.md` has the arithmetic.

**Rule 3 — Add headroom on every estimate.** *(estimate)*
Compaction, rebalance, traffic spikes, monitoring overhead. Note the documented formula already carries a 25% overhead factor and an 85% high-water mark — don't silently stack another arbitrary margin on top of those and call the result precise.

## Scale up vs scale out

Couchbase scales horizontally well, so the default answer is usually "scale out" (add more smaller nodes). But scale-up has its place:

| Scale UP (bigger nodes) | Scale OUT (more nodes) |
|---|---|
| Higher per-node throughput for read-heavy KV | Better fault tolerance |
| Simpler ops (fewer machines to manage) | Better for write-heavy workloads (more parallel writes) |
| Fewer moving parts to operate | Better headroom (lose one of N=10 vs one of N=3) |
| Limited by max node spec | Limited by cluster-wide coordination overhead, and by platform caps — Capella, for example, documents a maximum of 27 nodes per cluster |

**Default:** start with the smallest number of nodes that meets your fault-tolerance bar (3-node minimum for replica=1, 4+ for replica=2), then scale out as load grows.

## Service mix on nodes

Couchbase nodes can run any combination of services: **Data, Query, Index, Search, Eventing, Analytics, Backup**. (The Search Service is the full-text and vector search service; "FTS" is the older name for it.) Couchbase Server 8.0 allows Index, Query, Search, Analytics, Eventing and Backup to be added to or removed from a node dynamically, without a node add/remove cycle.

**Documented minimum memory quotas per service** ([Memory](https://docs.couchbase.com/server/current/learn/buckets-memory-and-storage/memory.html)):

| Service | Minimum quota |
|---|---|
| Data | 256 MB |
| Index | 256 MB |
| Search | 256 MB |
| Eventing | 256 MB |
| Analytics | 1024 MB |

These are floors for the service to start, not sizing targets. Three common deployment patterns:

**Pattern: all-services on every node.** Simplest. Each node runs everything. Good for small clusters (< 5 nodes) where dedicated service nodes would be wasteful.

**Pattern: Data nodes + Query/Index nodes.** Most common at moderate scale. Separate the data plane (KV-heavy, latency-sensitive) from the query plane (CPU-heavy, can absorb bursts). 3 data nodes + 2 query/index nodes is a common starting shape.

**Pattern: dedicated nodes per service.** Production at scale. Data nodes do nothing but data. Index nodes are RAM-heavy. Analytics nodes have their own boxes entirely (they're storage-heavy). Eventing has its own pool sized to function memory + concurrency.

`nodes.md` covers the math for picking the mix.

## Capella vs self-managed sizing differences

For Capella, sizing translates to picking **service groups** and their node configurations:

- A *service group* is a set of nodes running a specified set of Couchbase services, with its own compute instance type and disk configuration
- You pick the compute instance type (which determines vCPUs and memory per node) and the node count per service group
- Storage type and IOPS are configurable within what the cloud provider offers (AWS gp3 / io2 with configurable IOPS; GCP PD-SSD with IOPS derived from capacity; Azure Premium SSD / Ultra disk)
- The Data Service is mandatory and cannot be removed
- Documented node limits: **minimum 3 nodes** for a Data service group, **minimum 2** for other services, **maximum 27 nodes per cluster**
- Replication and backup are managed by Capella

`capella.md` covers the selection logic. **This skill does not quote Capella prices, credits, or cost figures** — those change and are the customer's commercial conversation, not a sizing input.

For self-managed, you control everything: CPU, RAM, disk, network. All references apply.

## Common mistakes to flag

When the user proposes a size, check for these:

- **Sizing for total data, not working set** — typically 2-5x over-provisioned
- **Forgetting replicas** — `replica=1` doubles the storage and RAM requirement for the data
- **No headroom for node failure** — if N=3 and one fails, the remaining 2 absorb 150% of normal load
- **Ignoring index memory** — GSI indexes use RAM; vector and FTS indexes are RAM-heavy. Plan for them as a separate budget
- **Mixing service types without budget** — Data, Query, and Index on the same node compete for RAM; explicit budgets are needed
- **Sizing for steady-state without considering burst** — a Black Friday e-commerce site needs 3-5x the steady-state capacity
- **Forgetting growth** — sizing for today means re-sizing in 6 months; size for 12-18 months projected
- **Ignoring rebalance overhead** — a rebalance moves data while the cluster is under normal load. Need to leave I/O and CPU slack for it
- **Assuming replicas serve reads** — they don't. An ordinary `get` always goes to the active vBucket. Replicas buy availability and durability, not read throughput. Adding a replica to "scale reads" is a sizing error
- **Ignoring the storage engine** — a Couchstore bucket wants a memory quota of at least 10% of its dataset; a Magma bucket at least 1%. Magma is Enterprise Edition only, and is the recommended engine as of Couchbase Server 8.0
- **Quoting a number you haven't verified** — if a throughput, latency or multiplier figure isn't from Couchbase documentation or the customer's own measurement, don't put it in a sizing

## Related skills

- `couchbase-data-modeling` — document shape decisions (embedding vs reference, array width) directly affect document size estimates, which are inputs to sizing math
- `couchbase-mcp` — operating the cluster once sized and provisioned
- `couchbase-migration-execution` — sizing the target cluster before beginning a migration
- `couchbase-ai-applications` — the retrieval design behind a vector workload, before budgeting index memory for it
- `couchbase-capella` — turning the resulting numbers into Service Groups and a Capella tier
- `couchbase-fts` — Search index design, which determines what the Search Service actually holds in memory
- `couchbase-kubernetes` — expressing the node count, memory and disk as a `CouchbaseCluster` CRD
- `couchbase-magma` — storage engine behavior and tuning behind the Magma sizing formulas
- `couchbase-performance-tuning` — checking whether tuning solves it before adding capacity
- `couchbase-xdcr` — the replication topology whose bandwidth you are planning for

## Version and edition gating

Sizing advice must state which version and edition it assumes:

- **Magma storage engine** — Enterprise Edition only; recommended engine as of 8.0, where new EE buckets default to the 128-vBucket Magma configuration (minimum bucket quota 100 MiB; the 1024-vBucket Magma configuration requires 1 GiB)
- **Memory-optimized index storage** — Enterprise Edition only. Standard (disk-optimized) index storage is available in both editions — on Plasma in EE, ForestDB in CE
- **Hyperscale and Composite vector indexes** — 8.0+
- **Memcached buckets** — removed in 8.0
- **Scopes and collections** — 7.0+
