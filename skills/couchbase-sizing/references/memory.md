# Memory and working set

Memory is the most consequential sizing dimension in Couchbase. Get this wrong and the cluster either over-provisions or under-provisions (degraded performance, eviction storms). This reference walks through the math.

> **Documented values are cited; heuristics are labelled.** Anything marked *(estimate)* is a field rule of thumb, not a Couchbase-documented figure — present it to the user as an estimate and replace it with a measurement as soon as one exists.

## Contents

- [What needs to fit in RAM](#what-needs-to-fit-in-ram)
- [The documented memory equation for the Data service](#the-documented-memory-equation-for-the-data-service)
- [Ejection policy choice](#ejection-policy-choice)
- [Working set assumptions](#working-set-assumptions)
- [Bucket RAM quota — what it actually is](#bucket-ram-quota--what-it-actually-is)
- [Multiple buckets](#multiple-buckets)
- [Compaction and rebalance RAM](#compaction-and-rebalance-ram)
- [Memory pressure symptoms](#memory-pressure-symptoms)
- [Quick decision tree](#quick-decision-tree)

## What needs to fit in RAM

Couchbase nodes hold these things in RAM:

1. **Working set of documents** — the subset of documents actively being read/written. This is the dominant consumer
2. **Per-document metadata** — a documented **56 bytes per document**, plus the document ID, held in RAM under value-only ejection; ejected with the document under full ejection
3. **The bucket's RAM quota overhead** — small but non-zero
4. **GSI indexes** — if the Index service is on this node
5. **Search / vector indexes** — if the Search Service is on this node
6. **Query service workspace** — query execution uses RAM for sorts, aggregates, joins
7. **Eventing function memory** — if Eventing is on this node
8. **System overhead** — OS, monitoring, replication buffers

**What is documented** ([Memory](https://docs.couchbase.com/server/current/learn/buckets-memory-and-storage/memory.html)):

- Allocate **no more than 90% of a node's memory** across all Couchbase services — **80% on nodes with a small amount of total memory**. The rest is for the OS.
- Minimum service quotas: **Data 256 MB, Index 256 MB, Search 256 MB, Eventing 256 MB, Analytics 1024 MB.** These are floors to start the service, not sizing targets.
- Eviction water marks default to **low 75% / high 85%** of the bucket quota. When usage hits the high mark the Data Service ejects items until it falls back to the low mark.

**A starting split for a small all-services node** *(estimate — derive the real split from the per-service math in this skill, not from these percentages)*:

- ~60% Data service (KV)
- ~20% Index service (if GSI is heavy)
- ~10% Query / Search / Eventing workspace
- ~10% system + headroom

For larger clusters with dedicated nodes, the allocation per service is much more skewed.

## The documented memory equation for the Data service

This is Couchbase's published formula — use it, and cite it, rather than improvising ([Sizing Guidelines](https://docs.couchbase.com/server/current/install/sizing-general.html)):

```
cluster_RAM_quota = (total_metadata + working_set) × (1 + overhead_percentage) / high_water_mark

  total_metadata = documents_num × (metadata_per_document + ID_size) × no_of_copies
  working_set    = total_dataset × working_set_percentage
```

Documented constants:

| Constant | Value |
|---|---|
| `metadata_per_document` | 56 bytes |
| `high_water_mark` | 85% (0.85) |
| `overhead_percentage` | 25% (0.25) |
| `no_of_copies` | `1 + replica_count` |

Three things worth stressing:

- **The metadata term includes the document ID size.** A 40-byte key adds 40 bytes per copy per document — at scale that is comparable to the 56 bytes itself. Keys like `user::0000000000000042` are not free.
- **The result is a cluster-wide quota.** Divide by data node count at the end to get per-node.
- **`no_of_copies` multiplies the metadata, and `working_set` is the whole replicated dataset.** Replicas are not free in RAM.

Storage engine sets a floor on top of this: a **Couchstore** bucket's quota should be at least **10%** of its expected dataset size, a **Magma** bucket's at least **1%** ([Memory](https://docs.couchbase.com/server/current/learn/buckets-memory-and-storage/memory.html)). The docs give a worked example: 5 TiB of data on Magma requires a minimum of 51 GiB RAM. If the formula above gives you less than the engine floor, the floor wins.

### Worked example 1: small app

Inputs:
- 1M documents
- Avg doc size: 2 KB
- Working set: 100% (small enough to all fit)
- Replica count: 1
- 3 data nodes
- All-services nodes

Assume ~20-byte document IDs.

```
working_set    = 1,000,000 × 2 KB × 1.0                  = 2.0 GB
total_metadata = 1,000,000 × (56 + 20) bytes × 2 copies  ≈ 152 MB
cluster_quota  = (152 MB + 2.0 GB) × 1.25 / 0.85         ≈ 3.2 GB cluster-wide
per_node       = 3.2 GB / 3                              ≈ 1.1 GB per node
```

Note the working-set term already covers only one copy of the data in this simplification — if you want replicas resident too, multiply `working_set` by `no_of_copies` as well. Plus index/query/eventing budgets and the OS: a 4 GB node would be tight; **8 GB nodes** are comfortable.

### Worked example 2: medium SaaS

Inputs:
- 100M documents
- Avg doc size: 1 KB
- Working set: 20% (most users are inactive at any moment)
- Replica count: 1
- 5 data nodes
- GSI on same nodes

Assume ~24-byte document IDs.

```
working_set    = 100M × 1 KB × 0.2                      = 20 GB
total_metadata = 100M × (56 + 24) bytes × 2 copies      = 16 GB   ← the ID doubles this term
cluster_quota  = (16 GB + 20 GB) × 1.25 / 0.85          ≈ 53 GB cluster-wide
per_node       = 53 GB / 5                              ≈ 10.6 GB per node
```

Plus GSI, plus other services, plus the OS. **32 GB nodes** give comfortable headroom.

Note how the metadata term is now comparable to the working set — and how much of it is the key, not the 56-byte constant. **Shortening document keys is a real RAM lever at this scale.** This is also the point where the eviction policy choice starts to matter.

### Worked example 3: large with cold tail

Inputs:
- 1B documents
- Avg doc size: 500 bytes
- Working set: 5% (long tail of inactive)
- Replica count: 1
- 10 data nodes
- Dedicated data nodes (no Index or Search Service)

Assume ~20-byte document IDs.

```
working_set    = 1B × 500 bytes × 0.05                  = 25 GB
total_metadata = 1B × (56 + 20) bytes × 2 copies        = 152 GB   ← dominant
cluster_quota  = (152 GB + 25 GB) × 1.25 / 0.85         ≈ 260 GB cluster-wide
per_node       = 260 GB / 10                            = 26 GB per node
```

At this scale the metadata term dominates, and the answer is to change the **ejection policy** and the **storage engine** rather than to buy RAM.

Under **full ejection**, the entire document — metadata and key included — is ejected, so RAM tracks the working set rather than the total document count. Combined with **Magma** (whose documented memory-to-data floor is 1%, against Couchstore's 10%), a corpus of this shape becomes far cheaper in RAM. **Magma is Enterprise Edition only.**

## Ejection policy choice

Couchbase buckets offer two ejection policies ([Memory](https://docs.couchbase.com/server/current/learn/buckets-memory-and-storage/memory.html)):

| Policy | What it ejects | Use |
|---|---|---|
| **Value-only** (default) | Document data only; keys and metadata stay resident | Latency-critical workloads with moderate document counts |
| **Full** | The entire document, including its metadata and keys | High document counts, and **the documented recommendation for Magma**, which is what lets Magma reach a memory-to-data ratio as low as 1% |

**Ephemeral buckets have a different pair entirely:** *no ejection* (refuse new data once the quota is reached) or *eject when RAM is full* (an NRU — not-recently-used — algorithm). Full ejection and value-only ejection are Couchbase-bucket concepts; don't apply their names to Ephemeral buckets.

The break-even is workload-dependent *(estimate)*: full ejection starts paying for itself once `documents × (56 + ID_size) × copies` is a large fraction of the RAM budget for a node. Compute the metadata term explicitly rather than using a document-count threshold.

## Working set assumptions

The working set fraction is the most uncertain input and the most consequential. Some heuristics:

The documented sizing example uses a `working_set_percentage` of **20%**, but that is an illustration, not a recommendation for your workload.

The table below is a **set of field heuristics** *(estimate)* — starting points for a conversation, never a substitute for measurement:

| Workload type | Starting working-set assumption *(estimate)* |
|---|---|
| Active session / cache layer | 80-100% |
| User profile / configuration | 30-60% |
| Transactional with hot recent data | 20-40% |
| Time-series with recent-window reads | 5-20% |
| Archive / cold storage | 1-5% |

**The only reliable working-set figure is a measured one.** On a running cluster, the resident-item ratio and cache-miss rate tell you what the working set actually is. Couchbase's access scanner regenerates its access log when the resident ratio drops below **95%**, which is a useful signal that the cluster is no longer fully resident.

**If you're not sure, model two scenarios** (say 30% and 60%) and present the requirement at each, explicitly labelled as assumptions.

## Bucket RAM quota — what it actually is

Each bucket has a RAM quota. This is the RAM the bucket is allowed to use **across the cluster**, not per node. A bucket with a 30 GB quota on a 3-node cluster uses up to 10 GB per node.

The cluster reserves this much regardless of whether the bucket actually has data — over-allocating bucket quota wastes RAM for no benefit.

**Documented minimum bucket quotas** depend on the storage engine and vBucket configuration ([Storage Engines](https://docs.couchbase.com/server/current/learn/buckets-memory-and-storage/storage-engines.html)):

| Engine / configuration | Minimum bucket RAM quota |
|---|---|
| Couchstore | 100 MiB |
| Magma, 128 vBuckets | 100 MiB |
| Magma, 1024 vBuckets | 1 GiB |

The 128-vBucket Magma configuration is **the default for new buckets in Couchbase Server Enterprise Edition 8.0 and later** — which is what dropped the Magma floor from 1 GiB to 100 MiB and made Magma practical for small buckets. Magma is **Enterprise Edition only**; Couchstore is the only engine in Community Edition.

## Multiple buckets

When you have multiple buckets on the same cluster, they share total RAM. The sum of bucket quotas across all buckets must fit within the cluster's RAM budget for the Data service.

Common allocation *(estimate)*: split quotas roughly proportional to data size or write rate, leaving some total RAM unallocated so the Data Service has slack.

Buckets are a heavyweight resource. Couchbase documents a **maximum of 30 buckets per cluster** ([Size Limits](https://docs.couchbase.com/server/current/learn/clusters-and-availability/size-limitations.html)), each carrying its own quota and per-node bookkeeping, and Couchbase also documents **0.2 CPU cores per bucket** per node. Many small buckets is both a resource and a ceiling problem — consolidate into **scopes and collections** (Couchbase Server 7.0+) instead.

## Compaction and rebalance RAM

Both compaction (background) and rebalance (during topology changes) consume additional resources beyond steady state. Couchbase does not publish a fixed multiplier for either, and the real figure depends on data size, write rate, disk speed and how much of the dataset moves — **so don't quote one.**

What the documented formula does give you is the 25% overhead factor and the 85% high-water mark, which together provide meaningful slack. If you rebalance frequently, plan additional headroom on top, or accept that rebalances will be slower because they are throttled by available resources. Measure a rebalance in staging at realistic data volume before committing to a production window.

## Memory pressure symptoms

When the cluster doesn't have enough RAM:

- **Resident item ratio falls** — the clearest signal. Couchbase's access scanner treats a ratio below **95%** as the point at which it regenerates its access log
- **Cache miss ratio climbs** — reads increasingly go to disk
- **Disk reads increase** — the cluster is paging cold data in on every miss
- **Latency p99 spikes** — paging is much slower than RAM access
- **Memory used approaches the high water mark (85% of quota)** — above it, the Data Service actively ejects items until usage falls back to the low water mark (75%)

If you're seeing these in production, add RAM. The cluster is under-sized for its working set.

## Quick decision tree

- **Calculating from scratch?** Use the documented formula: `(total_metadata + working_set) × 1.25 / 0.85`, where `total_metadata = docs × (56 + ID_size) × copies`. Then divide by node count
- **Metadata term looks huge?** Check the document ID size — it's inside the formula and it's often half the term. Shorter keys are a real RAM saving
- **Don't know the working set?** Model two scenarios and label both as assumptions; get a resident-ratio measurement as soon as there's a running cluster
- **Metadata dominating at high document counts?** Full ejection + Magma (Enterprise Edition). Magma's documented memory-to-data floor is 1% vs Couchstore's 10%
- **Ephemeral bucket?** Different ejection options entirely — no-ejection or NRU-based eviction; value-only/full don't apply
- **Multiple buckets?** Remember the 30-bucket cluster maximum and the 0.2 cores-per-bucket cost. Use scopes and collections instead where you can
- **Resident ratio dropping below 95%?** The cluster is no longer fully resident. Decide deliberately whether that's expected for this workload
- **Sizing for cluster growth?** Project 12-18 months out; changing node memory is more disruptive than adding nodes
