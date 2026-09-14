# Data plane — KV, sub-document, SQL++, and Search

The working surface of the official Couchbase MCP server: reading and writing documents, querying with SQL++, and running Search (FTS) queries. Every tool here addresses a keyspace explicitly as Bucket → Scope → Collection.

## Contents

- [Keyspace addressing](#keyspace-addressing)
- [Key-value operations](#key-value-operations)
- [Sub-document operations](#sub-document-operations)
- [SQL++ queries](#sql-queries)
- [Schema inference](#schema-inference)
- [Search (FTS)](#search-fts)
- [Scope and collection management](#scope-and-collection-management)
- [Decision tree](#decision-tree)

## Keyspace addressing

There are no ambient keyspace defaults. Nearly every tool takes `bucket_name`, `scope_name` and `collection_name` as explicit arguments. Discover before you address:

```
get_buckets_in_cluster            -> ["travel-sample", "orders"]
get_scopes_in_bucket              -> ["_default", "inventory"]
get_collections_in_scope          -> ["airline", "airport", "route"]
get_scopes_and_collections_in_bucket   -> both at once, as a scope -> collections map
```

`get_scopes_and_collections_in_bucket` is usually the right single call — one round trip for the whole bucket layout. Note that `get_collections_in_scope` requires the cluster to have the Query Service.

## Key-value operations

The cheapest path to a document when you know its ID.

| Tool | What it does | Mode |
|---|---|---|
| `get_document_by_id` | Fetch one document by ID. Raises if not found | read |
| `lookup_subdocument` | Read named paths inside a document without fetching it whole | read |
| `upsert_document_by_id` | Insert or replace by ID — idempotent | **write** |
| `insert_document_by_id` | Insert only; fails if the ID already exists | **write** |
| `replace_document_by_id` | Replace only; fails if the ID does not exist | **write** |
| `delete_document_by_id` | Delete by ID. Irreversible | **write** |
| `mutate_subdocument` | Modify named paths inside an existing document | **write** |

All write tools are **absent entirely** when `CB_MCP_READ_ONLY_MODE=true` (the default). See `safety.md`.

**Choosing among the three whole-document writes.** `upsert_document_by_id` when the desired end state is "this document, whatever was there before". `insert_document_by_id` when an accidental overwrite must fail loudly — registration flows, idempotency keys. `replace_document_by_id` when the document must already exist and you want a missing-document mistake to surface rather than silently create.

A read call:

```json
{
  "bucket_name": "travel-sample",
  "scope_name": "inventory",
  "collection_name": "airline",
  "document_id": "airline_10"
}
```

A write adds `document_content` (a JSON object):

```json
{
  "bucket_name": "travel-sample",
  "scope_name": "inventory",
  "collection_name": "airline",
  "document_id": "airline_10",
  "document_content": {"name": "40-Mile Air", "country": "United States"}
}
```

## Sub-document operations

Sub-document operations touch only the named paths, so they avoid transferring and rewriting the whole document. They are the right tool for a field inside a large document — and the wrong tool when you do not already know the exact path.

**Never guess a path.** A guessed path that does not exist returns a per-path error, not the data — and reporting "not found" for a wrong guess is worse than fetching the whole document. Learn the shape first, from `get_document_by_id`, `get_schema_for_collection`, or the user naming the field.

### Reading — `lookup_subdocument`

Three independent path lists, at least one required:

- `get_paths` — fetch the value at each path.
- `exists_paths` — check presence without transferring the value. Cheaper when a yes/no answer is all you need.
- `count_paths` — number of elements in the array or object at each path. Fails per-path if the target is neither.

```json
{
  "bucket_name": "travel-sample", "scope_name": "inventory",
  "collection_name": "hotel", "document_id": "hotel_10025",
  "get_paths": ["name", "address.city"],
  "exists_paths": ["vacancy"],
  "count_paths": ["reviews"]
}
```

Paths use Couchbase dot/bracket syntax: `address.city`, `tags[0]`, `tags[-1]` for the last element. Keep the combined path count across all three lists at 16 or fewer — Couchbase caps sub-document operations per call server-side.

### Writing — `mutate_subdocument`

The document **must already exist**; use `upsert_document_by_id` first if it might not. Operations arrive as separate keyword lists rather than one spec array:

`upsert_specs`, `insert_specs`, `replace_specs`, `remove_paths`, `array_append_specs`, `array_prepend_specs`, `array_insert_specs`, `array_add_unique_specs`, `counter_specs`, plus `create_parents` to create missing intermediate objects.

```json
{
  "bucket_name": "travel-sample", "scope_name": "inventory",
  "collection_name": "hotel", "document_id": "hotel_10025",
  "upsert_specs": [{"path": "lastReviewed", "value": "2026-09-14"}],
  "counter_specs": [{"path": "reviewCount", "delta": 1}],
  "array_append_specs": [{"path": "tags", "value": "verified"}]
}
```

**Atomicity**: a mutate call is all-or-nothing. If any single spec fails — an `insert` on a path that already exists, a counter on a non-numeric path — the entire call fails and nothing is applied. That is a feature, but it means a batch of unrelated edits fails as a unit; split them if partial progress is acceptable.

## SQL++ queries

SQL++ is the Couchbase query language. N1QL is a legacy alias for the same language.

| Tool | What it does | Mode |
|---|---|---|
| `run_sql_plus_plus_query` | Execute a SQL++ statement within a scope | read or **write**, depending on the statement |
| `explain_sql_plus_plus_query` | EXPLAIN the statement and evaluate the plan | read |

### Scope context

`run_sql_plus_plus_query(bucket_name, scope_name, query, named_parameters)` sets the query context to that bucket and scope. Write **bare collection names**:

```sql
SELECT name, country FROM airline WHERE country = $country LIMIT 10   -- correct
SELECT * FROM `travel-sample`.inventory.airline WHERE ...             -- wrong here
```

Double-qualifying inside an already-scoped context is the most common mistake with this tool.

### Named parameters

Bind values through `named_parameters` against `$name` placeholders. Concatenating user input into the statement string is a SQL++ injection path — do not do it.

```json
{
  "bucket_name": "travel-sample", "scope_name": "inventory",
  "query": "SELECT name FROM airline WHERE country = $country AND icao = $icao",
  "named_parameters": {"country": "United States", "icao": "MLA"}
}
```

### The read-only write guard

When `CB_MCP_READ_ONLY_MODE=true`, `run_sql_plus_plus_query` still exists but parses each statement and blocks anything that is not purely read-only. The guard is **deny-by-default**: a statement passes only if every top-level statement matches the read-only allow-list (SELECT, INFER, ADVISE and similar). Anything else is refused with a label:

- `data` — DML (INSERT, UPDATE, DELETE, UPSERT, MERGE)
- `structure` — DDL (CREATE / DROP / ALTER of indexes, scopes, collections)
- `privilege` — DCL (GRANT, REVOKE)
- `write` — any other non-read statement class

Do not try to phrase around the guard. If the user genuinely needs a write, say the server is in read-only mode and let them decide.

### EXPLAIN

`explain_sql_plus_plus_query` prefixes `EXPLAIN` automatically unless the statement already has it. It returns more than a raw plan:

```json
{
  "query": "...",
  "explain_statement": "EXPLAIN ...",
  "query_context": {"bucket_name": "...", "scope_name": "..."},
  "plan": { ... },
  "plan_evaluation": { ... }
}
```

`plan_evaluation` is the server's own findings on the plan — start there rather than reading the operator tree by hand. Interpretation guidance is in `diagnostics.md`.

## Schema inference

`get_schema_for_collection(bucket_name, scope_name, collection_name)` runs an `INFER` query server-side and returns the inferred structure of the collection.

This is the right answer to "what is in this collection?" — better than `SELECT * LIMIT 5`, because INFER samples and reports field paths, types and how consistently each field appears, rather than handing back a few raw documents to eyeball. Use it before composing queries against an unfamiliar collection, and before choosing index keys.

## Search (FTS)

Three read-only tools. **Requires Couchbase Server 7.6+ and the Search Service.** Vector search is not supported by these tools.

| Tool | What it does |
|---|---|
| `list_fts_indexes` | List Search indexes, optionally filtered |
| `get_fts_index_definition` | Full definition of one index — mappings, analyzers, plan params |
| `run_fts_query` | Run a Search query, or fetch its execution plan |

### Cluster-level vs scope-level indexes

`list_fts_indexes` filtering follows the two index models:

- **No filters** → cluster-level ("legacy") indexes only, the original pre-scoped model.
- **`bucket_name` only** → scope-level indexes across every scope in that bucket.
- **`bucket_name` + `scope_name`** → scope-level indexes in that one scope.
- **`scope_name` alone** → invalid; returns an error.

Entries carry `bucket` and `scope`, which are `null` for cluster-level indexes. Pass those same values back to `get_fts_index_definition` — **both** for a scoped index, **neither** for a cluster-level one. Do not reuse a bucket-only listing filter: `get_fts_index_definition` rejects a bucket without a scope.

### Running a query

`run_fts_query(index_name, query, ...)` takes the raw FTS query JSON body, passed through to the Search Service. Any non-vector query type works:

```json
{"match": "ale", "field": "type"}
{"conjuncts": [{"match": "ale"}, {"term": "beer", "field": "type"}]}
{"query": "type:beer +name:ale"}
```

Options map to the Search API: `limit` (default 10), `skip`, `fields`, `sort`, `facets`, `highlight_fields`, `disable_scoring`, and `raw` as a passthrough.

**Confirm the index before querying it.** A field-scoped query against a field the index does not map matches nothing rather than erroring — a silent wrong answer. If you do not already know what the index maps and how its fields are analyzed, call `get_fts_index_definition` first.

`explain=true` fetches the execution plan instead of results. Note that the Search Service exposes the plan per matched hit, not as a separate dry-run, so `explain=true` **still executes the query**; `limit` defaults to 1 in that mode, and the other options are ignored.

### FTS or SQL++?

Prefer `run_fts_query` for relevance-scored, fuzzy, phrase, wildcard or otherwise linguistic matching — anything wanting scores, highlighting or facets. SQL++ can invoke Search through the `SEARCH()` predicate, but the dedicated tool keeps the Search-specific result shape intact and makes it clear what was searched. Prefer SQL++ for exact predicates, joins, aggregation and projection.

## Scope and collection management

Four **write** tools, absent under the default read-only mode. **Couchbase Server 7.6+ and Capella.**

| Tool | Notes |
|---|---|
| `create_scope` | New scope in a bucket |
| `create_collection` | New collection in an existing scope |
| `delete_scope` | Deletes the scope **and every collection in it**. Permanent |
| `delete_collection` | Deletes the collection **and every document in it**. Permanent |

Both delete tools are irreversible without a backup. Read `safety.md` before composing either call.

There is no bucket management here — creating, editing or deleting a bucket is cluster administration and belongs in the Couchbase Web Console, `couchbase-cli`, or the Management REST API (Capella: the Capella Management API v4).

## Decision tree

- **One document, ID known** → `get_document_by_id`
- **A few known fields of a large document** → `lookup_subdocument`
- **Change a few known fields in place** → `mutate_subdocument`
- **Write a whole document** → `upsert` / `insert` / `replace_document_by_id`, chosen by the failure mode you want
- **Query across documents, exact predicates** → `run_sql_plus_plus_query`
- **Relevance-scored or fuzzy text matching** → `run_fts_query`
- **"What does this collection look like?"** → `get_schema_for_collection`
- **"What buckets/scopes/collections exist?"** → `get_scopes_and_collections_in_bucket`
- **"Why is this query slow?"** → `explain_sql_plus_plus_query`, then `diagnostics.md`
- **Anything that writes, drops or deletes** → `safety.md` first
