# Index sizing — GSI, Search, and vector

Indexes are often the second-largest RAM consumer after the working set. Vector indexes especially can dominate. This reference covers what is documented, what has to be measured, and how to plan Index and Search nodes.

> **Read this first.** Couchbase does **not** publish general size-per-document formulas for GSI, Search or vector indexes. The per-entry overheads and expansion factors that circulate in sizing conversations are folklore, and this reference no longer repeats them. Everything below is either a cited documented value or an explicit instruction to measure. That is a worse answer than a formula only if the formula is right.

## Contents

- [Index storage modes — pick this before sizing anything](#index-storage-modes--pick-this-before-sizing-anything)
- [GSI (secondary index) sizing](#gsi-secondary-index-sizing)
- [Search Service index sizing](#search-service-index-sizing)
- [Vector index sizing](#vector-index-sizing)
- [Eventing memory](#eventing-memory)
- [Analytics memory and storage](#analytics-memory-and-storage)
- [Putting it all together: a typical sizing exercise](#putting-it-all-together-a-typical-sizing-exercise)
- [Common index-sizing mistakes](#common-index-sizing-mistakes)
- [Quick decision tree](#quick-decision-tree)

## Index storage modes — pick this before sizing anything

Couchbase has two GSI storage modes, and they have completely different memory profiles ([Storage Modes](https://docs.couchbase.com/server/current/learn/services-and-indexes/indexes/storage-modes.html)):

| Mode | How it works | Memory implication | Edition |
|---|---|---|---|
| **Standard** (default) | Indexes saved on disk in a disk-optimized format, using both memory and disk for update and scan | "The total size of the index can be much bigger than the amount of memory available in each index node" | Both — **Plasma** in Enterprise Edition, **ForestDB** in Community Edition |
| **Memory-optimized** | Lock-free skiplist; **all index data kept in memory** | Index service quota must hold every resident index. Index updates **pause at 95% of quota** | **Enterprise Edition only** |

This choice is cluster-wide and set at cluster initialization, and it is the single biggest input to Index node sizing:

- With **standard** storage, the Index service quota is a working-set budget, not a total-index budget. Index size can exceed RAM.
- With **memory-optimized** storage, the Index service quota must exceed the total size of all resident indexes, with margin — hitting 95% stalls index maintenance.

Couchbase Server 8.0 adds configurable hole-punching granularity for Plasma-based standard indexes, improving disk reclamation.

## GSI (secondary index) sizing

An index entry holds the indexed value(s), a reference back to the document, and structural overhead. Index replicas multiply the whole thing.

**There is no documented per-entry overhead constant.** Size GSI empirically:

1. Build the intended index on a **representative sample** in a staging cluster — representative in field cardinality and value length, not just document count
2. Read the index's actual size from the Index service statistics
3. Extrapolate linearly to the full document count (GSI size grows roughly linearly with indexed document count)
4. Multiply by `1 + index_replica_count`

This takes an afternoon and produces a number you can defend. A formula with an invented 80-byte constant does not.

What you can say without measuring:
- **Index size scales with the number of indexed documents**, so projected document growth translates directly into index growth
- **Wider composite indexes are larger** — each additional key adds its value to every entry
- **Index replicas are full copies** — an index with one replica costs twice the storage and twice the memory
- **Partial indexes are smaller** — a `WHERE` clause on the index definition excludes documents entirely

### When indexes hurt more than help

- Each index is updated on every write to the indexed collection, so index count multiplies write-side work on the Index service
- Unused indexes (created speculatively) are pure cost — check last-used statistics and drop them
- Wide composite indexes are larger and more expensive to maintain

Use the Index Advisor (`ADVISE` in SQL++, or the Index Advisor in the UI) against your representative query set to derive the minimum useful index set rather than guessing.

## Search Service index sizing

The Search Service builds an inverted index plus whatever fields you choose to store. Size is driven by the analyzer chain (tokenization, stemming, n-grams), the number of indexed fields, and how many fields are stored verbatim.

**Couchbase does not publish an expansion factor for this, and the variance between analyzer configurations is large enough that a single multiplier would be misleading.** Measure it:

1. Build the intended index definition — the real one, with the real analyzers — on a representative sample
2. Read the resulting index size
3. Extrapolate to the full corpus

Things that push Search index size up: n-gram analyzers, storing fields for highlighting, multiple language analyzers, and synonym collections. Couchbase Server 8.0 adds **synonym searches**, **custom document filters** (replacing default type identifiers), **partition selection** at query time, and **BM25** as a scoring option alongside tf-idf — the first two of which affect index size.

Search indexes can be disk-resident with parts paged into RAM. Allocate disk beyond the measured index size for write-time buffering and compaction.

## Vector index sizing

Vector indexes are typically the largest single line item in a sizing. Couchbase Server **8.0** introduces three vector index types ([What's New in 8.0](https://docs.couchbase.com/server/current/introduction/whats-new.html)):

| Index type | What it is | Where it lives |
|---|---|---|
| **Hyperscale vector index** | A single vector column, documented as handling "billions of documents with low memory footprint" | Index service (GSI), created via SQL++ |
| **Composite vector index** | Combines vector columns with scalar columns for filtered vector search | Index service (GSI), created via SQL++ |
| **Search vector index** | Hybrid search combining vectors with text and geospatial capabilities | Search Service |

All three are **8.0+**. On a 7.x cluster, only the Search Service's vector capability from the 7.6 line is available — gate the advice.

SQL++ gains `CREATE`/`ALTER`/`DROP` statements for Hyperscale and Composite vector indexes, plus the vector functions `APPROX_VECTOR_DISTANCE`, `VECTOR_DISTANCE`, `ISVECTOR`, `ENCODE_VECTOR`, `DECODE_VECTOR` and `NORMALIZE_VECTOR`.

### The one part you can compute

The **raw embedding payload** is arithmetic and is safe to state:

```
raw_vector_bytes = document_count × dimensions × bytes_per_dimension
```

For float32 embeddings that is 4 bytes per dimension:

| Dimensions | 1M docs | 10M docs | 100M docs |
|---|---|---|---|
| 384 | ~1.5 GB | ~15 GB | ~150 GB |
| 768 | ~3 GB | ~30 GB | ~300 GB |
| 1024 | ~4 GB | ~40 GB | ~400 GB |
| 1536 | ~6 GB | ~60 GB | ~600 GB |
| 3072 | ~12 GB | ~120 GB | ~1.2 TB |

This is the **floor**, not the index size. The index structure itself adds overhead on top, and **Couchbase does not publish an overhead factor for either Hyperscale or Composite indexes.** Do not invent one.

### How to size a vector index properly

1. Compute the raw embedding payload from the table above — this is your floor and it is already large enough to shape the conversation
2. Build the intended index type on a representative sample (hundreds of thousands to low millions of vectors is usually enough)
3. Measure the actual index size and the memory it occupies
4. Extrapolate, then add headroom for growth

Hyperscale is specifically documented as the low-memory-footprint option for very large single-vector-column corpora; Composite is the one to use when you need scalar filtering alongside the vector. That is the selection criterion — choose on the access pattern, then measure the size.

### Reducing vector index size

- **Lower-dimensional embeddings** — the raw payload scales linearly with dimensions, so a 1024-dim model against a 1536-dim one is a third smaller before any index overhead
- **Index fewer documents** — if half the corpus is archived and never searched, don't index it. A filtered index is the cheapest optimization available
- **Choose the right index type** — Hyperscale for a large single vector column, Composite when scalar filtering is part of the query
- **Quantization** — check the current vector index documentation for what quantization options your server version supports before assuming any

## Eventing memory

The documented **minimum Eventing service quota is 256 MB** — a floor to start the service, not a sizing target.

Each deployed function's footprint is a function of its worker count and what the function code actually does. **Couchbase does not publish a per-function or per-worker memory figure**, and the range between a trivial filter function and one building large intermediate structures is wide enough that a generic number would mislead.

Size Eventing empirically:

1. Deploy the real functions at the intended worker count in staging
2. Drive a representative mutation rate through them
3. Measure the Eventing service's memory use
4. Add headroom for the JavaScript runtime's allocation churn and for functions you expect to add

Couchbase Server 8.0 adds scope-level Eventing configuration, a **`num_nodes_running`** setting to control how many nodes execute a function per scope, and an **OnDeploy** handler that runs once at deployment before mutation processing begins. `num_nodes_running` in particular is a direct lever on the aggregate Eventing memory footprint.

## Analytics memory and storage

**First, establish which product is meant.** There are two, and they size differently:

- The **Analytics Service** running as a service within a Couchbase Server cluster. Its documented **minimum memory quota is 1024 MB** — the highest of any service, and still only a floor
- **Capella Analytics** / **Couchbase Enterprise Analytics** — separate analytics products with their own deployment and sizing model and their own documentation. (The name "Capella Columnar" is retired; it is Capella Analytics now.)

For the in-cluster Analytics Service: it maintains its own copies of the ingested data, so storage scales with the datasets it shadows, and memory scales with query complexity — joins and large aggregations need far more than scans. Couchbase does not publish per-node RAM guidance for it, so **derive the number from a representative workload in staging** rather than from a node-size rule of thumb.

Analytics is usually placed on dedicated nodes (Pattern C in `nodes.md`) because its resource profile is so different from OLTP.

## Putting it all together: a typical sizing exercise

The shape of a real sizing exercise, for a workload of 100M documents (1 KB average, 20% working set, replica=1), 5 GSI indexes, one Search index over a text-heavy field, one vector index over 10M 768-dimension embeddings, and 3 Eventing functions:

**Step 1 — compute what the documented formula covers.** The Data service RAM quota, from `memory.md`:

```
total_metadata = 100M × (56 + ID_size) × 2 copies
working_set    = 100 GB × 0.2 = 20 GB
cluster_quota  = (total_metadata + working_set) × 1.25 / 0.85
```

**Step 2 — compute the vector floor.** `10M × 768 × 4 bytes ≈ 30 GB` of raw embeddings. This is the floor for the vector index and it already tells you the Search or Index nodes carrying it need to be the largest in the cluster.

**Step 3 — measure everything else.** GSI size, Search index size, actual vector index size including structural overhead, and Eventing function footprint all come from building them on a representative sample in staging. There is no documented formula to substitute here, and a guessed one would dominate the total.

**Step 4 — place services.** Once you have measured numbers, the placement follows: Data nodes sized by the formula, Index and Search nodes sized by the measured index sizes plus growth, Eventing sized by the measured function footprint. Service separation keeps a large vector index from forcing every node in the cluster to be large — which is usually the main argument for Pattern B or C in `nodes.md`.

**The useful output of step 1 and step 2 is that they bound the conversation before anyone builds anything.** They are not the sizing.

## Common index-sizing mistakes

- **Ignoring vector index size** — the raw embedding payload alone (10M × 1536-dim float32 ≈ 60 GB) usually dominates the whole sizing, before any index overhead
- **Quoting an index overhead factor you can't source** — Couchbase publishes none for GSI, Search or vector indexes. Measure instead of multiplying
- **Sizing GSI for current data, not projected** — index size grows with indexed document count
- **Forgetting index replicas** — an index replica is a full copy; it doubles both storage and memory for that index
- **Not deciding the index storage mode first** — memory-optimized storage (Enterprise Edition only) requires the Index quota to hold *every* resident index and stalls index maintenance at 95% of quota; standard storage doesn't
- **Building many indexes "just in case"** — each costs memory and write throughput. Use the Index Advisor
- **Assuming Search indexes are small** — analyzer configuration drives the size, and n-grams or stored fields can change it substantially

## Quick decision tree

- **Sizing GSI?** Build it on a representative sample, measure, extrapolate, × `(1 + index_replicas)`. No published per-entry constant exists
- **Which index storage mode?** Standard (default, both editions) unless you have a specific reason for memory-optimized — which is Enterprise Edition only and must hold every index in the Index quota
- **Sizing Search?** Build the real index definition on a sample and measure. Analyzer choice dominates
- **Sizing vector?** Compute the raw floor (`docs × dims × 4` for float32), then measure the actual index. Hyperscale for a large single vector column, Composite when you need scalar filtering. Both **8.0+**
- **Sizing Eventing?** Deploy the real functions in staging at the intended worker count and measure. Minimum service quota is 256 MB; `num_nodes_running` (8.0+) controls how many nodes run a function
- **Many indexes, constrained RAM?** Drop unused ones; use the Index Advisor on a representative query set
- **Vector index too large?** Fewer dimensions, index fewer documents, or the more memory-efficient index type
- **Analytics?** Establish whether it's the in-cluster Analytics Service (minimum quota 1024 MB) or Capella Analytics / Couchbase Enterprise Analytics — they size differently. Dedicated nodes either way
