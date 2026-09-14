# Access patterns — modeling for query, search, and vector search

## Contents

- [The fundamental tradeoff](#the-fundamental-tradeoff)
- [Modeling for SQL++ queries](#modeling-for-sql-queries)
- [Modeling for the Search Service](#modeling-for-the-search-service-full-text-search)
- [Modeling for vector search](#modeling-for-vector-search)
- [When to pre-aggregate](#when-to-pre-aggregate)
- [Quick decision tree](#quick-decision-tree)

The single biggest lever for query performance isn't index choice — it's document shape. A query that fits the document's natural structure runs orders of magnitude faster than one that fights it. This reference covers how to model documents so the queries you actually run are fast.

## The fundamental tradeoff

You have three knobs that trade against each other:

1. **Read speed** — how fast a typical query returns
2. **Write speed / cost** — how expensive each write is (more denormalization = more places to update)
3. **Storage** — how much disk/memory the data takes (denormalization = duplication)

You don't get to optimize all three. Pick two; accept the third.

For most apps, the right answer is: **optimize reads, accept some write cost, accept some storage cost** — in most OLTP workloads reads substantially outnumber writes. Measure your own ratio before committing to it; a telemetry ingest path is the opposite shape.

## Modeling for SQL++ queries

### Index-friendly document shape

If you'll filter by a field, the field should be:

1. **At a stable path** — don't bury it under varying object structures. `user.tier` is good; `user.attributes[where name='tier'].value` is awful
2. **At the top level when possible** — `tier: "gold"` queries faster than `details.tier: "gold"` because index entries are smaller
3. **Consistently typed** — `age: 42` (number) vs `age: "42"` (string) breaks indexes

### Covering indexes

When EXPLAIN shows a `Fetch` operator after an index scan, the index doesn't cover the query — the query had to fetch the full document to read fields beyond the indexed ones.

Cover the query by indexing all fields in the SELECT and WHERE:

```sql
CREATE INDEX ix_user_tier_cover ON users(tier, name, email);
SELECT name, email FROM users WHERE tier = 'gold';  -- now covered
```

One index has to carry everything — a query cannot be covered by two indexes working together. `META().id` is covered implicitly.

Document shape implication: keep fields you commonly project together near each other in your mental model so it's natural to include them in the same index.

### Composite predicates

If you frequently filter by A AND B, a composite index `ON collection(A, B)` is much faster than separate indexes on A and B.

Document shape implication: when you know two fields will always be queried together, make sure both are flat top-level fields (not nested inside different sub-objects).

### Array indexes

If a document has an array and you query by elements of that array:

```json
{ "id": "user::42", "tags": ["premium", "early-access", "us-west"] }
```

```sql
CREATE INDEX ix_user_tags ON users(DISTINCT ARRAY t FOR t IN tags END);
SELECT META().id FROM users WHERE ANY t IN tags SATISFIES t = "premium" END;
```

Modeling consequence worth knowing up front: `ANY ... SATISFIES` works against either a `DISTINCT ARRAY` or an `ALL ARRAY` index. `UNNEST` works against either as well, but only `ALL ARRAY` can **cover** it — `UNNEST` emits one row per element without de-duplicating, and a `DISTINCT` index has already collapsed duplicates, so the plan has to fetch the document to re-unnest it. Bare `EVERY` cannot use an array index at all. If your access pattern flattens the array into rows and you want to avoid the fetch, model for `ALL ARRAY`.

Cost: array indexes are larger and slower to update than scalar indexes. Use them only if you'll actually query by array contents.

Document shape implication: design arrays for query frequency. Frequently-queried arrays should be flat (`tags: ["a", "b"]`), not array-of-objects (`tags: [{name: "a"}, {name: "b"}]`).

## Modeling for the Search Service (full-text search)

The Search Service is for: free-form text matching, fuzzy matching, phrase queries, faceted search, and hybrid queries combining text, geospatial and vector predicates. It is not for plain exact-match or range queries — those belong to the Query service and a GSI.

### Field design for Search

- **Searchable text fields should be strings or arrays of strings**, not nested objects
- **Don't index every field in the Search index** — pick the fields users actually search over
- **Use distinct fields for distinct purposes**: a `title` field separate from a `description` field lets you boost matches in the title

Example for a product catalog:

```json
{
  "name": "Pacific Northwest Cabernet 2020",
  "description": "Full-bodied red wine with notes of cherry...",
  "tags": ["red", "cabernet", "pacific northwest", "2020"],
  "tasting_notes": "cherry, oak, vanilla"
}
```

Index `name` and `description` as text with the standard analyzer; index `tags` as keyword (exact match, no tokenization); leave `tasting_notes` out of the Search index if it's only for display.

### Analyzers and the multi-field pattern

The same field can be indexed multiple ways. Couchbase calls these "type mappings." For example, you might want `name`:
- Tokenized (so "Pacific" matches a search for "pacific")
- Lower-cased (so "pacific" matches "PACIFIC")
- And also keyword-indexed (so you can do exact-match facets like "show me all docs where name is exactly X")

Document shape implication: don't duplicate the field in the document just because you want multiple indexes on it. Use the Search index's type mapping to handle multiple analyses of the same source field.

### Synonyms

The Search Service supports synonym sources: the synonym definitions live as documents in a regular collection, and a Search index references that collection. Check your release's documentation for availability before designing around it.

For modeling purposes:

- A synonym set is a separate document in its own collection; don't denormalize synonyms into product documents
- Synonyms apply at the Search index level, so design one synonym source per language or domain rather than per document type

## Modeling for vector search

Couchbase Server **8.0** offers three vector index types, all **Enterprise Edition** (and available on Capella):

| Type | What it is | Created with |
|---|---|---|
| **Hyperscale vector** | Indexes a single vector column; fastest and lowest memory at very large scale | `CREATE VECTOR INDEX` |
| **Composite vector** | A GSI with one vector key plus scalar keys, so scalar filters narrow the candidate set first | `CREATE INDEX` with a `VECTOR` key |
| **Search vector** | Vector support in the Search Service, for hybrid text + geo + vector queries; documented as suited to roughly 100 million documents | Search index definition |

The documented starting point is a Hyperscale index; move to Composite when you need scalar pre-filtering, or to a Search vector index when you need hybrid text/geo/vector queries.

The model in every case: store the embedding as a field in the document, then index that field.

### Where to put the embedding

```json
{
  "id": "product::sku-12345",
  "name": "Pacific Northwest Cabernet 2020",
  "description": "Full-bodied red wine...",
  "embedding": [0.012, -0.034, 0.156, ...]
}
```

The embedding is a top-level field, an array of floats. The vector index targets `embedding` by name.

### Embedding dimension

`dimension` is a required option in the index's `WITH` clause and must match exactly what your embedding model produces — check the model provider's own documentation for the number, and re-check it when you change models, since providers ship models at several dimensions and some allow truncation.

Once the index exists, every document it indexes must carry an embedding of that same dimension.

The other `WITH` option worth deciding at modeling time is `similarity`: `COSINE`, `DOT`, `L2` / `EUCLIDEAN`, or `L2_SQUARED` / `EUCLIDEAN_SQUARED` (the default). Pick the metric your embedding model was trained for — normalizing vectors and then switching metrics after the fact means rebuilding the index.

### Embedding storage cost

Work it out from first principles rather than from a rule of thumb: a float32 embedding of N dimensions is N x 4 bytes in the document. At 1536 dimensions that is 6144 bytes, roughly 6 KB per document, or about 6 GB of raw embedding across a million documents — before the index's own copy.

The index side is smaller than the raw vectors, because the `description` option applies quantization (the default is `IVF,SQ8`). That is a modeling lever: heavier quantization trades recall for footprint.

If storage is a constraint, you can use lower-dimensional models or store embeddings only for documents that will actually be searched (skip embedding for archived docs).

### Hybrid retrieval pattern

Vector search alone is often not enough — you need to combine semantic similarity with hard filters. Two patterns:

**Pattern A — Composite vector index: scalar filter, then vector search in one statement.**

This is what the Composite vector index exists for. The scalar keys narrow the set, and the vector search runs over what's left.

```sql
SELECT META().id, name
FROM products
WHERE category = 'wine' AND year > 2018
ORDER BY APPROX_VECTOR_DISTANCE(embedding, $query_vec, "COSINE")
LIMIT 10;
```

Use `APPROX_VECTOR_DISTANCE()`, not `VECTOR_DISTANCE()`. `VECTOR_DISTANCE()` exists but does not use the vector index — it brute-forces the scan.

**Pattern B — Search vector index for genuinely hybrid queries.**

When the other predicates are themselves text or geospatial rather than simple scalars, model for a Search vector index and let the Search Service score text and vector together.

Document shape implication in both cases: the scalar fields you'll filter by need to be top-level and consistently typed so they can be index keys alongside the vector. Don't bury `category` under `metadata.classifications.category`.

### Multimodal embeddings

If a document has multiple things you want to search over (e.g., a product has a name embedding AND a description embedding AND a picture embedding), store each as a separate field and create a vector index per field:

```json
{
  "id": "product::sku-12345",
  "name_embedding": [...],         // index 1: vector search by name semantic
  "description_embedding": [...],  // index 2: vector search by description
  "image_embedding": [...]         // index 3: visual similarity
}
```

This is more storage but lets you search each modality independently or in combination.

## When to pre-aggregate

If a single read needs to combine many documents (e.g., "monthly sales totals" requires summing 100K orders), don't do that at read time. Pre-aggregate via:

- **Materialized summary documents** updated by Eventing functions
- **Periodic batch jobs** that compute aggregates and write summary docs
- **The Analytics service** (EE), or the standalone Capella Analytics / Couchbase Enterprise Analytics products, for ad-hoc aggregation isolated from the operational workload

Pre-aggregation is a denormalization pattern. See `document-shape.md` for the tradeoffs.

## Quick decision tree

- **Filter by exact value or range?** → SQL++ with a covering GSI; field needs to be top-level and stable-pathed
- **Free-form text search?** → the Search Service with an appropriate analyzer; don't try to make the Query service do this
- **Semantic / similarity search at scale?** → Hyperscale vector index (8.0+, EE) on the embedding field
- **"Find similar AND filter by a scalar"?** → Composite vector index (8.0+, EE)
- **"Find similar AND match text or geo"?** → Search vector index
- **Need to aggregate many documents per read?** → pre-aggregate (Eventing, a batch job, or Analytics — all EE)
- **Schema has fields that vary by record type?** → don't index those; index only the stable fields
