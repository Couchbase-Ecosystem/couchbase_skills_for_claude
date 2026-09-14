# Vector search with the Search Service

- [What it is](#what-it-is)
- [Which index type](#which-index-type)
- [Document structure](#document-structure-for-vector-search)
- [Defining a vector field](#defining-a-vector-field-in-a-search-index)
- [Running a kNN query](#running-a-knn-query)
- [Pre-filtering](#pre-filtering-a-knn-query)
- [Hybrid search](#hybrid-search-text--vector)
- [Generating embeddings](#generating-embeddings)
- [Sizing](#sizing-vector-indexes)
- [Limitations and gotchas](#limitations-and-gotchas)

## What it is

Vector search (kNN — k-nearest neighbours) finds documents whose stored embedding vectors are closest to a query vector in high-dimensional space. The typical use case is semantic search: convert a query to an embedding using a language model, then find documents whose embeddings are nearby.

The Search Service supports vector search through a **Search Vector Index** — a field of type `vector` inside an ordinary Search index. This is available from Couchbase Server **7.6.0 on Linux and 7.6.2 on macOS**; it is **not supported on Windows**. It is available in Community Edition as well as Enterprise Edition and Capella.

## Which index type

From Couchbase Server 8.0, there are two other vector index types, both owned by the **Index Service** rather than the Search Service, and both **Enterprise Edition / Capella only**:

| | Search Vector Index | Composite / Hyperscale Vector Index |
|---|---|---|
| Service | Search Service | Index Service (GSI) |
| Query interface | Search request with `knn` | SQL++ `APPROX_VECTOR_DISTANCE()` |
| Hybrid with text / geo queries | Yes, in one index | No |
| Documented scale ceiling | tens of millions, up to roughly 100 million documents | tens of millions to billions |
| Version | 7.6+ | 8.0+ |

Stay on the Search Vector Index when you need hybrid text + vector (or geo + vector) in a single query. Move to Hyperscale or Composite when the corpus outgrows the Search Service or when the retrieval belongs inside a SQL++ query. See `couchbase-ai-applications/references/vector-index-types.md` for the full comparison.

The rest of this page is about the Search Vector Index.

## Document structure for vector search

Store the embedding as a JSON array of numbers in your document:

```json
{
  "id": "doc::001",
  "title": "Introduction to Couchbase",
  "description": "A primer on the Couchbase data platform...",
  "embedding": [0.023, -0.147, 0.891]
}
```

Guidelines:

- The array must be a flat list of numbers — no nested arrays, no nulls.
- All vectors indexed by one vector field must have the same dimension. Mixed dimensions break the index.
- The field must be reachable by a mapping path in the index definition.

## Defining a vector field in a Search index

A vector field is declared in the index's type mapping like any other field, with `type: "vector"`:

```json
"embedding": {
  "fields": [{
    "name": "embedding",
    "type": "vector",
    "dims": 1536,
    "similarity": "dot_product",
    "vector_index_optimized_for": "recall",
    "index": true
  }]
}
```

**`dims`** — must match your embedding model's output dimension. From Couchbase Server 7.6.2, the Search Service supports arrays of up to **4096** elements.

**`similarity`** — pick one and use it consistently:

| Value | Use when | Notes |
|---|---|---|
| `dot_product` | Embeddings are unit-normalized | Equivalent to cosine on normalized vectors |
| `l2_norm` | Models that use Euclidean distance | Different geometry than dot product |
| `cosine` | Embeddings are not guaranteed normalized | Available from Couchbase Server **7.6.4+** |

Match the metric to your embedding model's recommended metric. Using the wrong one produces wrong rankings.

**`vector_index_optimized_for`:**

- `recall` — higher accuracy, larger index, slower build. Use for production search quality.
- `latency` — faster queries, lower recall. Use for real-time autocomplete or latency-critical paths.
- `memory-efficient` — smaller memory footprint; available from Couchbase Server **7.6.4+**.

Verify the exact property names and allowed values against the Search child-field options reference for your server version before scripting index creation.

## Running a kNN query

A vector search is an ordinary Search request with a `knn` array:

```python
run_fts_query(
    index_name="products-vector-idx",
    query={
        "knn": [
            {
                "field": "embedding",
                "vector": [0.023, -0.147, 0.891],  # query embedding, same dimension
                "k": 10
            }
        ]
    },
    limit=10,
    bucket_name="shop",
    scope_name="catalog",
)
```

`k` is the number of nearest neighbours the index is asked for; `size` trims the final result set. Set `k >= size`, and typically 3–5× `size`, for reasonable recall.

A `knn` entry may also carry a `boost` (its weight in a hybrid query) and a `params` object for index-specific tuning. Check the Search request reference for the tuning parameters your version exposes rather than copying values from elsewhere.

## Pre-filtering a kNN query

A `knn` entry can carry a `filter` — an ordinary Search query that restricts which documents the kNN search considers, applied *before* the nearest-neighbour search:

```json
"knn": [{
  "field": "embedding",
  "vector": [0.023, -0.147, 0.891],
  "k": 10,
  "filter": { "field": "color", "match": "navy" }
}]
```

This is the Search Service's answer to metadata-filtered semantic search. The filtered fields must be mapped in the same index. Confirm `filter` support on your server version — it is documented for current releases but was not in the original 7.6.0 vector search feature set.

## Hybrid search (text + vector)

Put both a `query` object and a `knn` array in the same Search request against an index that maps both the text fields and the vector field:

```python
run_fts_query(
    index_name="products-hybrid-idx",
    query={
        "knn": [
            {"field": "embedding", "vector": [0.023, -0.147, 0.891], "k": 50, "boost": 1.0}
        ],
        "query": {"match": "fast delivery", "field": "description", "boost": 0.5}
    },
    limit=10,
    bucket_name="shop",
    scope_name="catalog",
)
```

How the two halves combine: the Search Service unions the `knn` results with the `query` results (an OR), and documents that match *both* rank higher. Use the `boost` values to shift the balance between semantic and lexical relevance. Do not assume a specific arithmetic formula for the combined score — it is not a documented contract, and it changes with the scoring model.

On 8.0+, consider setting the index's `scoring_model` to `bm25`; the documentation calls out BM25 as better suited to hybrid search than the default `tf-idf`, and as more consistent across index partitions.

Hybrid search is the one thing only the Search Vector Index does. The Index-Service vector indexes do not combine with full-text or geospatial queries.

## Generating embeddings

The MCP server and the Search Service do not generate embeddings — that is your application's job (or, on licensed AI Data Plane deployments, the Data Processing Service; see `couchbase-ai-applications`).

Your indexing pipeline:

1. Generate an embedding for each document at write time, in your application or an ETL job.
2. Store the embedding array in the document alongside the text fields.
3. At query time, embed the query string with the same model, then issue the `knn` search.

**Important:** always use the same embedding model for indexing and querying. Changing models means re-embedding every document and rebuilding the index. Record the model name and the embedding timestamp in the document so you can find stale vectors later.

## Sizing vector indexes

Vector index data lives in the Search Service's memory quota, not in Data Service RAM. The raw vector payload alone is:

```
raw vector bytes = num_documents x dimension x bytes_per_element
```

A 32-bit float element is 4 bytes, so one million 1536-dimension vectors is roughly 6 GB of raw vector data before any index structure, storage format, or per-document overhead. Actual index size depends on `vector_index_optimized_for`, the rest of the index mapping, and the number of partitions and replicas — treat the raw figure as a floor, not an estimate, and measure on a representative subset before sizing a cluster. See `couchbase-sizing` for the full method.

## Limitations and gotchas

- **Platform:** vector search runs on Linux (7.6.0+) and macOS (7.6.2+). Not supported on Windows.
- **Dimension limit:** 4096 elements per vector field from 7.6.2. Models producing larger vectors can't be indexed directly — reduce dimensionality first.
- **No null vectors:** documents missing the embedding field are not returned by vector search. Make sure every document has the field, or scope the index to documents that do.
- **Index rebuild on dimension change:** there is no in-place resize. Switching embedding models means re-embedding every document and rebuilding the index.
- **`k` is not the result count:** `k` is how many neighbours the index returns; `size` trims the response. Setting `k` very large costs latency without improving the top results.
- **Edition:** the Search Vector Index works in Community Edition, but **Search index replicas are Enterprise Edition / Capella only** — plan availability accordingly.
