# Search Service troubleshooting

The Search Service was formerly called Full Text Search; "FTS" survives in tool names and REST paths.

- [Diagnostic workflow](#diagnostic-workflow)
- [Index not returning expected documents](#index-not-returning-expected-documents)
- [Index not updating / stale results](#index-not-updating--stale-results)
- [Slow queries](#slow-queries)
- [Common error messages](#common-error-messages)
- [Rebuilding an index](#rebuilding-an-index)

## Diagnostic workflow

When Search isn't working as expected, work through this sequence before diving into specifics:

1. **`admin_fts_index_doc_count(index_name)` and `admin_fts_index_stats(index_name)`** — is the index healthy? Compare the indexed document count against what you expect, and read the outstanding-mutations figure from the stats (it should fall to near 0 when caught up).
2. **`admin_fts_index_list()`** — does the index exist? Right bucket/scope/collection? `admin_fts_index_get` returns the full definition (on the data-plane server, `list_fts_indexes` and `get_fts_index_definition`).
3. **`run_fts_query` with a simple `{"match_all": {}}`** — does the index return any results at all?
4. **`run_fts_query` with `explain=true`** — for a specific known document ID, why did it or didn't it match?

## Index not returning expected documents

### "No results" for a document you know exists

**Check 1: Is the document in the right scope/collection?**
The index sourceParams must match the scope and collection the document is in. List the index definition and compare to where the document lives.

**Check 2: Is the field indexed?**
If using static mapping (`default_mapping.enabled: false`), the field must be explicitly listed in the type mapping. A typo in the field name causes it to be silently skipped.

**Check 3: Is `doc_config.type_field` matching?**
If your index uses `type_field` doc_config mode, the document must have that field with the value you mapped. If the field is missing or the value doesn't match any type mapping, the document is indexed under `default_mapping` — which may be disabled. On 8.0+, a custom document filter on the index can also exclude documents; check that too.

**Check 4: Analyzer mismatch.**
You're using a `term` query (no analysis applied) but the field was indexed with a lowercasing analyzer. `term: "Active"` misses documents indexed as `"active"`. Either lowercase your term query value, or use a `match` query instead (which applies the field's analyzer at query time).

**Check 5: Index not caught up.**
A non-zero outstanding-mutations count means the index is behind. Wait for it to drain before declaring a document missing.

**Check 6: Vector query against a non-vector index.**
A `knn` clause only works against a Search index that maps a `vector` field. Vector fields require Couchbase Server 7.6+ (Linux 7.6.0, macOS 7.6.2; unsupported on Windows). Hyperscale and Composite vector indexes (8.0+, Enterprise Edition / Capella) are Index Service objects queried with SQL++ `APPROX_VECTOR_DISTANCE()`, not through `run_fts_query` — sending a `knn` request to their name will not find a Search index.

### "Fewer results than expected" for a text query

**Check 1: Operator is AND when you need OR.**
`match` defaults to OR. If you explicitly set `"operator": "and"`, all terms must be present. A query for "quick brown fox" with AND won't match a document that only has "quick fox."

**Check 2: Stopwords removed from query.**
The `en` analyzer removes common stop words. If the user's query is "is this a problem," it may be reduced to just "problem" after analysis. `match_phrase` is more fragile here.

**Check 3: Stemming mismatch.**
With `en` analyzer, "libraries" stems to "librari" and "library" also stems to "librari" — these match. But "library" and "lib" do not match (different stems). If you expect "lib" to match "library," you need fuzzy search or ngrams.

## Index not updating / stale results

**Check the outstanding-mutations count.**
A non-zero and growing value means the Search indexer is falling behind the mutation rate. Causes:

- Indexing too many fields (dynamic mapping, large documents) — reduce the index scope
- Search Service under-resourced (too little RAM or CPU) — check Search node stats
- A backfill in progress (bulk load or rebalance adding data faster than FTS can consume) — normal; wait for it to drain

**Check whether ingestion is paused.**
Index status reporting indicates whether ingestion has been paused. If it has, `admin_fts_index_ingest_resume` restarts it.

## Slow queries

**Use `explain: true` to see score breakdown and term matching.** Expensive at scale — use only in development.

**Check field cardinality.**
Wildcard and regexp queries (`*`, `?`, `.*`) expand to many terms at query time. On high-cardinality fields (millions of unique terms), this is slow. Rewrite as prefix queries if possible; prefix queries use the index's term dictionary efficiently.

**Reduce `k` for vector queries.**
kNN with a large `k` scans more index nodes. Start with `k = 3-5 × size` — don't set `k = 10000` to "be safe."

**Check Search Service RAM pressure.**
`admin_stats_single` / `admin_stats_multi`, called with Search Service metric names, return the service's memory usage. If the service is near its memory quota, query latency degrades. Increase the Search Service memory quota or add Search nodes. Vector fields are the usual culprit — vector data lives in the Search Service quota, not Data Service RAM.

**Check partition count.**
A single-partition index on a multi-node cluster does all its work on one node. Raising `planParams.indexPartitions` spreads indexing and query work. Note that on `tf-idf` scoring, partition count also affects relevance scores; on 8.0+ the `bm25` scoring model is more consistent across partitions.

## Common error messages

| Error | Cause | Fix |
|---|---|---|
| `index not found` | Wrong index name or the index was deleted | `admin_fts_index_list` (or `list_fts_indexes`) to get the real name |
| `no planPIndexes for indexName` | Index has no active pindexes — still building, or a node issue | Check `admin_fts_index_stats` |
| `timeout` | Query took too long | Simplify the query; check resource pressure; use `admin_fts_index_stats` to confirm ingestion isn't running a full rebuild |
| geopoint/field-type errors | Field mapped as text but used in a geo query | Fix the index definition — field type must be `geopoint` (points) or `geoshape` (GeoJSON) |
| vector/dimension errors on a `knn` request | Vector query sent to an index with no vector mapping, or query vector dimension differs from `dims` | Confirm the index maps a `vector` field and that the query vector has exactly the indexed dimension |

Error strings change between versions — match on the symptom, not the exact text.

## Rebuilding an index

Sometimes the right answer is a clean rebuild:

1. `admin_fts_index_delete(index_name)` — removes the index (no document data lost, just the search index)
2. Fix the definition
3. `admin_fts_index_create(...)` — recreate with the corrected definition
4. Monitor `admin_fts_index_stats` until the outstanding-mutations count drops to ~0

An index alias lets you point application queries at a stable name and swap the underlying index without a code change — the cleanest way to do a zero-downtime rebuild. Neither MCP server has a tool for aliases; create and repoint them through the Search REST API (`/api/index/{aliasName}`), `couchbase-cli`, or the Web Console.

Rebuilds can be disruptive. On large collections, Search indexing can take a long time — measure on a subset first. If the index is in production, create a new index with a different name, verify it, then swap the query target and delete the old one.
