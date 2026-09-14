# Search index design

The Search Service was formerly called Full Text Search; "FTS" survives in tool names, REST paths, and the `fulltext-index` index type.

- [Index definition anatomy](#index-definition-anatomy)
- [doc_config modes](#doc_config-modes)
- [Static vs dynamic mappings](#static-vs-dynamic-mappings)
- [Field types](#field-types)
- [Field options](#field-options)
- [Child field mappings](#child-field-mappings-nested-objects)
- [Scoring model](#scoring-model)
- [Partitions and replicas](#partitions-and-replicas)
- [Scoped vs legacy bucket-level index](#scoped-index-vs-legacy-bucket-level-index)
- [Memory and storage sizing](#memory-and-storage-sizing)
- [Common index design mistakes](#common-index-design-mistakes)

## Index definition anatomy

An FTS index definition has three layers:

```json
{
  "name": "my-index",
  "sourceType": "couchbase",
  "sourceName": "my-bucket",
  "sourceParams": { "scope": "my-scope", "collection": "my-collection" },
  "type": "fulltext-index",
  "params": {
    "doc_config": { "mode": "scope.collection.type_field", "type_field": "type" },
    "mapping": {
      "default_mapping": { "enabled": false },
      "types": {
        "my-scope.my-collection": {
          "enabled": true,
          "properties": {
            "title":       { "fields": [{ "name": "title", "type": "text", "analyzer": "en", "index": true }] },
            "description": { "fields": [{ "name": "description", "type": "text", "analyzer": "en", "index": true }] },
            "status":      { "fields": [{ "name": "status", "type": "keyword", "index": true }] },
            "price":       { "fields": [{ "name": "price", "type": "number", "index": true }] },
            "location":    { "fields": [{ "name": "location", "type": "geopoint", "index": true }] },
            "created_at":  { "fields": [{ "name": "created_at", "type": "datetime", "index": true }] }
          }
        }
      }
    }
  }
}
```

## doc_config modes

`doc_config.mode` controls how the Search Service identifies document types for type mapping:

| Mode | Behaviour | When to use |
|---|---|---|
| `type_field` | Reads a top-level field (e.g. `type`) from the document | Documents have a discriminator field |
| `docid_prefix` | Matches a key prefix (e.g. `user::`) | Key-namespaced collections |
| `docid_regexp` | Matches a regex on the document key | Complex key schemes |
| `scope.collection.type_field` | Scope + collection + type field (recommended for scoped indexes) | Scoped deployments (7.0+) |

For most 7.0+ deployments, use `scope.collection.type_field` and set `type_field` to the name of your document-type discriminator field (often `type`, `docType`, or `_type`).

## Static vs dynamic mappings

**Static mapping** (`default_mapping.enabled: false`, explicit `types`): only the fields you list are indexed. Predictable memory usage, faster indexing, smaller index. Use this in production.

**Dynamic mapping** (`default_mapping.enabled: true`): the Search Service indexes every field it finds. Fast to get started, terrible in production — indexes nested arrays, large string blobs, and fields you'll never search. Avoid on collections with varied or large document shapes.

**Hybrid**: static types with `dynamic: true` on specific sub-objects you want to index freely. Common for user-defined metadata fields within a known document structure.

## Field types

| Search field type | Best for | Notes |
|---|---|---|
| `text` | Searchable text — titles, descriptions, body copy | Requires an analyzer |
| `keyword` | Exact-match strings — status, category, country code | No analyzer; case-sensitive by default |
| `number` | Numeric range queries | Stored as a floating-point number |
| `datetime` | Date/time range queries | ISO 8601 string in the document |
| `boolean` | Boolean filter | True/false only |
| `geopoint` | Geo-distance, bounding-box and polygon queries | `{"lat": ..., "lon": ...}` or `"lat,lon"` string |
| `geoshape` | GeoJSON shape queries (point, linestring, polygon, circle, envelope, collections) | Document holds a GeoJSON geometry |
| `IP` | IP address / CIDR range queries | IPv4 or IPv6 string |
| `vector` | kNN vector search **inside** this Search index (7.6+) | Needs `dims` and `similarity`; see `vector-search.md` |
| `vector_base64` | Same as `vector`, with base64-encoded vectors | Check availability for your server version |

A `vector` field lives in the Search index itself — that is what a Search Vector Index *is*. The Hyperscale and Composite vector indexes (8.0+, Enterprise Edition / Capella only) are separate objects in the Index Service, created with SQL++, and are not part of a Search index definition.

## Field options

For `text` fields:

- `analyzer` — which analyzer to apply (see `analyzers.md`)
- `index: true` — field is searchable (default)
- `store: true` — field value can be retrieved in search results (increases index size)
- `include_term_vectors: true` — enables hit highlighting and phrase matching (increases index size)
- `include_in_all: true` — field participates in `_all` field (catch-all queries)
- `docvalues: true` — enables sorting and faceting on this field

For `keyword` fields, `docvalues: true` is usually correct if you plan to facet or sort by this field.

## Child field mappings (nested objects)

For a document field like `address.city`:

```json
"address": {
  "enabled": true,
  "dynamic": false,
  "properties": {
    "city":    { "fields": [{ "name": "city", "type": "keyword", "index": true }] },
    "country": { "fields": [{ "name": "country", "type": "keyword", "index": true }] }
  }
}
```

For arrays of objects, the Search Service flattens the array automatically — you don't need to do anything special. A query on `tags.label` matches if any element in the `tags` array has a matching `label`.

## Scoring model

From Couchbase Server 8.0, the index `mapping` object accepts a `scoring_model` property:

- `tf-idf` — the long-standing default.
- `bm25` — added in 8.0. The documentation recommends it for hybrid searches that combine vector and full-text retrieval, and notes it gives more consistent ranking across index partitions.

On earlier versions there is no choice: scoring is tf-idf. Note the documented caveat that tf-idf scores are affected by how many partitions the index has and how documents are distributed across them — one more reason to prefer `bm25` on 8.0+ for partitioned indexes.

## Partitions and replicas

Both live under `planParams` in the index definition:

- **`indexPartitions`** — how many partitions the index is split into across nodes running the Search Service. More partitions spread indexing and query work; they also affect tf-idf scoring, as above. The older `maxPartitionsPerPIndex` property is deprecated in favour of `indexPartitions`.
- **`numReplicas`** — full copies of the index for high availability. `0` disables replication; the documented maximum is **3** replicas. **Search index replicas are Enterprise Edition / Capella only** — in Community Edition, leave `numReplicas` at 0.

Do not hand-tune the `store` object (merge policy, persister behaviour, file format version) unless you have a specific reason; Couchbase sets sensible defaults from the rest of the index definition.

## Scoped index vs legacy bucket-level index

In Couchbase 7.0+, always create scoped indexes (specify `sourceName`, `scope`, and `collection` in the source params). Legacy bucket-level indexes index all documents in the bucket regardless of scope/collection — harder to maintain and can't use the `scope.collection.type_field` doc_config mode.

## Memory and storage sizing

Search index size depends heavily on the mapping, so measure rather than guess: build the index against a representative subset of the collection and extrapolate. Factors that increase it:

- `store: true` on text fields (stored fields add raw value storage)
- `include_term_vectors: true` (needed for highlighting and phrase matching — stores per-term positions)
- Dynamic mapping (everything gets indexed)
- Long text fields with many unique terms
- High cardinality keyword fields

Dedicated Search nodes should have enough RAM to hold the active working set of index data. See `couchbase-sizing/references/indexes.md` for the memory formula.

## Common index design mistakes

**Mistake: dynamic mapping in production.** Index only the fields you search. Dynamic mapping indexes everything — including nested metadata, large text blobs, and internal fields you'll never search.

**Mistake: wrong type for keyword fields.** Using `text` with the `keyword` analyzer is not the same as the `keyword` type. Use the `keyword` type for exact-match fields like `status`, `country`, `category`.

**Mistake: no `docvalues` on faceted or sorted fields.** Facets and sorting require `docvalues: true` on the field. If you add it after the index is built, you must rebuild the index.

**Mistake: indexing the same field twice under different names.** A field appears in results once per mapping. Having `title` in both a static mapping and the default dynamic mapping causes unexpected behaviour. Disable the default mapping when using static mappings.

**Mistake: forgetting to set the type_field.** If `doc_config.type_field` points to a field that doesn't exist in most documents, the Search Service falls back to the `default_mapping`. If `default_mapping.enabled: false`, those documents aren't indexed at all.

**Mistake: assuming replicas are available.** `numReplicas > 0` is an Enterprise Edition / Capella feature. On Community Edition a Search index has a single copy; a node loss takes its partitions offline until rebalance.
