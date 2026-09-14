# Search query types

Queries against the Search Service (formerly Full Text Search / FTS) go through the data-plane MCP tool `run_fts_query(index_name, query, bucket_name, scope_name, explain, limit, skip, fields, sort, facets, highlight_fields, disable_scoring, raw)`. Pass `bucket_name` and `scope_name` for a scoped index and neither for a cluster-level one; `limit` and `skip` are the paging controls.

The `query` parameter is a JSON object whose shape determines the query type. Two families:

- **Analytic queries** (`match`, `match_phrase`) run the field's analyzer over the query text before matching.
- **Non-analytic queries** (`term`, `terms`, `prefix`, `wildcard`, `regexp`, `bool`, ranges) match the indexed tokens directly, with no analysis.

Contents:

- [Simple queries](#simple-queries)
- [Range queries](#range-queries)
- [Compound queries](#compound-queries)
- [Geo queries](#geo-queries)
- [Match-everything and by-key queries](#match-everything-and-by-key-queries)
- [Query string syntax](#query-string-syntax)
- [Vector and hybrid queries](#vector-and-hybrid-queries)
- [Facets](#facets)
- [Boosting](#boosting)
- [Highlighting](#highlighting)
- [Score control](#score-control)
- [Search result shape](#search-result-shape)

## Simple queries

### Match query (most common)

Tokenizes the search string and matches against a text field. Uses the field's analyzer.

```json
{ "match": "quick brown fox", "field": "description" }
```

For multi-word input, `match` performs an OR by default (any term matches). Use `operator: "and"` to require all terms:

```json
{ "match": "quick brown fox", "field": "description", "operator": "and" }
```

### Match phrase query

All terms must appear in order with no intervening terms.

```json
{ "match_phrase": "quick brown fox", "field": "description" }
```

Requires `include_term_vectors: true` on the field at index time.

### Term query

Exact match — no analysis applied. Use for keyword fields.

```json
{ "term": "active", "field": "status" }
```

### Prefix query

Matches terms starting with the prefix.

```json
{ "prefix": "prod", "field": "category" }
```

### Wildcard query

`*` = any sequence, `?` = single character. Applied to the indexed terms (post-analysis).

```json
{ "wildcard": "cou?hbase", "field": "product" }
```

### Fuzzy query

Matches terms within a given edit distance (Levenshtein). `fuzziness: 1` or `2`.

```json
{ "match": "cuchbase", "field": "product", "fuzziness": 1 }
```

### Regexp query

Matches indexed terms against a regular expression (Bleve regexp syntax).

```json
{ "regexp": "cou.*ase", "field": "product" }
```

### Terms query

A phrase expressed as an explicit token list, with no analysis applied. Use when you already know the exact indexed tokens.

```json
{ "terms": ["quick", "brown", "fox"], "field": "description" }
```

### Boolean field query

Matches a `boolean`-typed field.

```json
{ "bool": true, "field": "in_stock" }
```

## Range queries

### Numeric range

```json
{ "min": 10.0, "max": 100.0, "inclusive_min": true, "inclusive_max": false, "field": "price" }
```

Omit `min` or `max` for open-ended ranges.

### Date range

```json
{
  "start": "2025-01-01T00:00:00Z",
  "end": "2025-12-31T23:59:59Z",
  "inclusive_start": true,
  "inclusive_end": false,
  "field": "created_at"
}
```

### Term range

Lexicographic range on keyword fields.

```json
{ "min": "apple", "max": "mango", "field": "product_name" }
```

### IP / CIDR range

Requires a field mapped with the `IP` type. Matches addresses inside a CIDR block.

```json
{ "cidr": "192.168.1.0/24", "field": "client_ip" }
```

## Compound queries

### Conjunction (AND)

All child queries must match.

```json
{
  "conjuncts": [
    { "match": "couchbase", "field": "description" },
    { "term": "active", "field": "status" }
  ]
}
```

### Disjunction (OR)

At least `min` child queries must match (default 1).

```json
{
  "disjuncts": [
    { "match": "couchbase", "field": "description" },
    { "match": "nosql", "field": "tags" }
  ],
  "min": 1
}
```

### Boolean query

Combines `must`, `should`, and `must_not` clauses.

```json
{
  "must":     { "conjuncts": [{ "term": "active", "field": "status" }] },
  "should":   { "disjuncts": [{ "match": "couchbase", "field": "description" }] },
  "must_not": { "disjuncts": [{ "term": "deleted", "field": "status" }] }
}
```

`must` is a hard filter. `should` contributes to score but isn't required. `must_not` excludes documents.

## Geo queries

Point-based geo queries need the field indexed as type `geopoint`. GeoJSON shape queries need the field indexed as type `geoshape`.

### Geo-distance (radius)

```json
{
  "location": { "lat": 37.7749, "lon": -122.4194 },
  "distance": "50km",
  "field": "location"
}
```

Distance unit options: `m`, `km`, `mi`, `nm`, `ft`.

### Geo-bounding-box

```json
{
  "top_left":     { "lat": 38.0, "lon": -123.0 },
  "bottom_right": { "lat": 37.0, "lon": -121.0 },
  "field": "location"
}
```

### Geo-polygon

```json
{
  "polygon_points": [
    { "lat": 37.9, "lon": -122.5 },
    { "lat": 37.9, "lon": -122.0 },
    { "lat": 37.5, "lon": -122.0 },
    { "lat": 37.5, "lon": -122.5 }
  ],
  "field": "location"
}
```

### GeoJSON shape query

Against a `geoshape` field, the Search Service supports GeoJSON geometries — `Point`, `LineString`, `Polygon`, `MultiPoint`, `MultiLineString`, `MultiPolygon`, `GeometryCollection`, plus Couchbase's `Circle` and `Envelope` shapes — with a spatial relation such as intersects, contains, or within. Check the geospatial section of the Search documentation for the exact relation names your server version accepts.

## Match-everything and by-key queries

```json
{ "match_all": {} }
```
Matches every document in the index — the first thing to run when debugging "no results."

```json
{ "match_none": {} }
```
Matches nothing. Useful as a placeholder in generated queries.

```json
{ "ids": ["doc::001", "doc::002"] }
```
Matches specific document keys. Check the exact property name (`ids` vs `docid`) against the Search request reference for your server version.

## Query string syntax

A single string with embedded operators, for user-facing search boxes and quick console testing:

```json
{ "query": "+description:couchbase -status:deleted title:nosql^3 price:>100" }
```

Supported operators include `+` (must), `-` (must not), `field:` prefixes, `\"...\"` for phrases, `^` for boost, and `>`/`<` for ranges. It is convenient but harder to validate than structured JSON — prefer structured queries for anything an application builds programmatically.

## Vector and hybrid queries

A Search request may carry a `knn` array alongside (or instead of) `query`, when the index maps a `vector` field. The `knn` entry takes `field`, `vector` (or a base64 form), `k`, an optional `boost`, and an optional `filter` that pre-restricts the candidate documents:

```json
{
  "query": { "match": "fast delivery", "field": "description" },
  "knn": [{
    "field": "embedding",
    "vector": [0.023, -0.147, 0.891],
    "k": 50,
    "filter": { "field": "status", "match": "active" }
  }]
}
```

The Search Service unions the `knn` and `query` results and ranks documents that satisfy both higher — it is not a documented weighted-sum formula, so tune with `boost` and measure rather than predicting scores. Vector fields are available in Search indexes from Couchbase Server 7.6 (Linux 7.6.0, macOS 7.6.2; not Windows).

## Facets

Facets are aggregations on the search result set. Pass them in the `facets` parameter:

```json
{
  "category_facet": { "size": 10, "field": "category" },
  "price_facet": {
    "size": 5,
    "field": "price",
    "numeric_ranges": [
      { "name": "cheap",    "max": 50 },
      { "name": "mid",      "min": 50, "max": 200 },
      { "name": "premium",  "min": 200 }
    ]
  }
}
```

Field must have `docvalues: true` in the index definition.

## Boosting

Add `boost` to any query clause to increase its relevance contribution:

```json
{
  "disjuncts": [
    { "match": "couchbase", "field": "title",       "boost": 3.0 },
    { "match": "couchbase", "field": "description", "boost": 1.0 }
  ]
}
```

## Highlighting

Pass `highlight: { "style": "html", "fields": ["title", "description"] }` to get highlighted snippets in results. Requires `include_term_vectors: true` on the fields.

## Score control

- `explain: true` in the request body to get a per-term score breakdown in results (expensive — debug only)
- `score: "none"` to skip scoring entirely and treat Search as a boolean filter (faster when you don't need ranking)
- Scoring model is an *index* setting, not a query setting: `mapping.scoring_model` is `tf-idf` by default, with `bm25` available from Couchbase Server 8.0 and recommended there for hybrid text + vector search.

## Search result shape

```json
{
  "total_hits": 1234,
  "hits": [
    {
      "id": "doc::001",
      "score": 1.87,
      "fields": { "title": "...", "status": "active" },
      "fragments": { "title": ["...highlighted <em>match</em>..."] },
      "locations": { "title": { "couchbase": [{ "pos": 1, "start": 0, "end": 9 }] } }
    }
  ],
  "facets": { "category_facet": { "terms": [...] } },
  "status": { "total": 1, "successful": 1, "failed": 0 }
}
```

The exact result envelope varies between server versions — read fields defensively rather than asserting a fixed shape. `fields` is only populated if you pass the `fields` parameter in the request. `fragments` requires `highlight`. `locations` requires `include_term_vectors`.
