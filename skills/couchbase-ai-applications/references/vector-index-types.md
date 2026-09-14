# Vector index types

- [The three types](#the-three-types)
- [Decision matrix](#decision-matrix)
- [Search Vector Index](#search-vector-index-svi)
- [Composite Vector Index](#composite-vector-index-cvi)
- [Hyperscale Vector Index](#hyperscale-vector-index-hvi)
- [Quantization and recall](#quantization-and-recall)
- [Choosing](#choosing)
- [Migration between types](#migration-between-types)

## The three types

Couchbase has three vector index types, owned by two different services, introduced in two different releases:

- **Search Vector Index (SVI)** — a `vector` field inside a Search Service index. Introduced in **Couchbase Server 7.6** (Linux 7.6.0, macOS 7.6.2; not supported on Windows). Available in **Community Edition** as well as Enterprise Edition and Capella.
- **Composite Vector Index (CVI)** — a Global Secondary Index in the Index Service with one vector column plus one or more scalar columns. Introduced in **Couchbase Server 8.0**. **Enterprise Edition / Capella only.**
- **Hyperscale Vector Index (HVI)** — a single-vector-column index in the Index Service, mostly resident on disk in an optimized format. Introduced in **Couchbase Server 8.0**. **Enterprise Edition / Capella only.**

The abbreviations SVI / CVI / HVI are convenient shorthand; the documented product names are the full ones above.

The single most consequential difference is the **query interface**. SVI is queried with a Search request carrying a `knn` array. CVI and HVI are queried with SQL++ using `APPROX_VECTOR_DISTANCE()`. Switching between the Search Service and the Index Service is an application change, not just an index change.

## Decision matrix

| | Search Vector Index | Composite Vector Index | Hyperscale Vector Index |
|---|---|---|---|
| **Service** | Search Service | Index Service (GSI) | Index Service (GSI) |
| **Version** | 7.6+ | 8.0+ | 8.0+ |
| **Edition** | CE, EE, Capella | EE / Capella | EE / Capella |
| **Documented scale** | tens of millions; documentation caps it around 100M documents | tens of millions to a billion | tens of millions to billions |
| **Memory profile** | held in the Search Service memory quota | moderate Index Service memory | low — most of the index lives on disk |
| **Scalar filtering** | `filter` inside the `knn` clause, applied before the kNN search | scalar predicates filter first, then vectors are compared on the survivors | scalars added with `INCLUDE`, compared alongside the vectors |
| **Hybrid with full-text / geo** | **Yes — the only type that does this** | No | No |
| **Created with** | Search index definition (`vector` field) | `CREATE INDEX ... (v VECTOR, scalar1, scalar2)` | `CREATE VECTOR INDEX ... (v VECTOR)` |
| **Queried with** | Search request with `knn` | SQL++ `APPROX_VECTOR_DISTANCE()` | SQL++ `APPROX_VECTOR_DISTANCE()` |
| **Similarity metrics** | `dot_product`, `l2_norm`; `cosine` from 7.6.4 | `COSINE`, `DOT`, `L2`/`EUCLIDEAN`, `L2_SQUARED`/`EUCLIDEAN_SQUARED` | same as Composite |
| **Dimension limit** | 4096 from 7.6.2 | not documented as a fixed cap — verify for your release | not documented as a fixed cap — verify for your release |

Note the distance-metric spellings differ between the two services. The Search Service uses `dot_product` / `l2_norm` / `cosine`; SQL++ uses `COSINE` / `DOT` / `L2` / `L2_SQUARED`. The SQL++ default when `similarity` is omitted is `L2_SQUARED`, which is not what most embedding models want — set it explicitly.

## Search Vector Index (SVI)

Defined as a `vector` field in an otherwise ordinary Search index, with `dims`, `similarity`, and `vector_index_optimized_for`. Because it lives in a Search index, the same index can also map text and geo fields — so one request can combine a `knn` clause with a `match` query and rank documents that satisfy both higher.

It also supports pre-filtering: a `knn` entry may carry a `filter` holding an ordinary Search query, and only matching documents are considered for nearest-neighbour search.

Use when:

- You need hybrid text + vector (or geo + vector) in a single query. Nothing else does this.
- You are already running the Search Service on the same collection.
- You are on 7.x, or on Community Edition, where the other two types are unavailable.
- The corpus is within the Search Service's documented range — tens of millions of documents, up to roughly 100 million.

Detailed field syntax and query shapes are in the `couchbase-fts` skill.

## Composite Vector Index (CVI)

A GSI containing one vector column and one or more scalar columns:

```sql
CREATE INDEX products_cvi
  ON `my-bucket`.`my-scope`.products (embedding VECTOR, category, status, region)
  WITH { "dimension": 1536, "similarity": "COSINE" };
```

The vector column can be the leading key or sit anywhere among the keys. The point of the type is that the scalar predicates narrow the candidate set *first*, and vector distances are only computed on what survives. That makes it the right choice when a filter removes most of the corpus — multi-tenant data, region-partitioned catalogues, status-gated content.

Query it in SQL++:

```sql
SELECT p.title, p.description
FROM `my-bucket`.`my-scope`.products AS p
WHERE p.category = "electronics"
  AND p.status = "active"
ORDER BY APPROX_VECTOR_DISTANCE(p.embedding, $query_vector, "COSINE")
LIMIT 10;
```

`LIMIT` pushes down into the index scan, so always supply one. `APPROX_VECTOR_DISTANCE()` is the approximate, index-backed function; `VECTOR_DISTANCE()` is the exact brute-force one — use it only on small result sets or to check recall.

**Critical:** the scalar fields you filter on must be index keys in the index definition. A predicate on a field the index doesn't carry cannot be used to narrow the scan.

## Hyperscale Vector Index (HVI)

A single-vector-column index designed for the largest corpora, with most of the index held on disk in an optimized format rather than in RAM:

```sql
CREATE VECTOR INDEX color_desc_hyperscale
  ON `my-bucket`.`my-scope`.documents (embedding VECTOR)
  WITH { "dimension": 1536, "similarity": "COSINE", "description": "IVF,SQ8" };
```

Queried the same way as a Composite index, with SQL++ and `APPROX_VECTOR_DISTANCE()`.

**Algorithm.** The documentation describes the Hyperscale index as using the IVF (inverted file) clustering algorithm together with quantization. Couchbase's own launch material describes it as a hybrid that combines graph-based and cluster-based approaches — Microsoft's Vamana work combined with IVF. It is **not** an HNSW index. Do not assert a more specific internal structure than that.

**Scalar filtering.** Scalars can be attached with the `INCLUDE` clause on `CREATE VECTOR INDEX`. Included values are stored with the vectors but are not themselves indexed; predicates on them cut down how many vector comparisons are needed, without accelerating the predicate itself. That is a different mechanism from the Composite index's indexed scalar keys — for filters that eliminate most of the dataset, Composite is generally the better fit.

**Reranking (8.0).** A Hyperscale index persists full vectors by default (`persist_full_vector`), which lets a query re-score its candidates against the full-precision vectors instead of the quantized ones. Reranking is off by default and is enabled per-query through `APPROX_VECTOR_DISTANCE()`. It costs throughput and increases index size, and it only helps when quantization is what is limiting recall — measure both ways.

Use when:

- The corpus is large enough that memory-resident indexes are impractical.
- Retrieval is unfiltered or lightly filtered.
- The retrieval belongs inside a SQL++ query alongside other logic.

The documentation's own default advice is to try a Hyperscale index first and move to another type if it doesn't meet your needs.

## Quantization and recall

Both Index-Service types accept a `description` string in the `WITH` clause that sets the clustering and quantization scheme — the number of IVF centroids plus either scalar quantization (SQ4 / SQ6 / SQ8) or product quantization (`PQ<subquantizers>x<bits>`). Related knobs include `train_list` (how many vectors are sampled to train the index) and `scan_nprobes` (how many cells a scan probes).

Directionally, and per Couchbase's best-practice guidance:

- Fewer bits per value (SQ4, or PQ) means a smaller index and lower recall; more bits means larger and more accurate. SQ8 is the usual starting point.
- More probes per scan means better recall and lower throughput.
- More partitions reduces build time and per-node memory; more replicas raises throughput and lowers latency at the cost of memory.

Do not treat any specific QPS, latency, or recall number as portable. Published benchmark figures come from a particular dataset, dimension count, hardware profile and cluster shape, and will not predict your workload. Build a small representative index, measure recall against a ground-truth set, and tune from there.

## Choosing

Work down this list and stop at the first match:

1. **Do you need text or geo relevance combined with vector similarity in one query?** → Search Vector Index. Nothing else can do it.
2. **Are you on 7.x, or on Community Edition?** → Search Vector Index. Composite and Hyperscale need 8.0 and Enterprise Edition or Capella.
3. **Does a scalar predicate eliminate most of the corpus on nearly every query** (tenant, region, status, product line)? → Composite Vector Index.
4. **Otherwise** → Hyperscale Vector Index, which is also the documentation's default recommendation. Fall back to Composite if you measure it short on your workload.

## Migration between types

There is no in-place conversion — the index type is fixed at creation, and moving between the Search Service and the Index Service also changes the query API. Migrate by running both:

1. Create the new index alongside the existing one.
2. Wait for it to finish building.
3. Change the application's retrieval path (Search request to SQL++, or the reverse) behind a flag, and compare results against the old path on a sample of real queries.
4. Cut traffic over, then drop the old index.

Budget for step 3. A Search request with `knn` and a SQL++ `ORDER BY APPROX_VECTOR_DISTANCE()` return different result shapes and different score semantics — a distance where the Search Service gives a relevance score — so downstream ranking and thresholds usually need retuning, not just re-plumbing.
