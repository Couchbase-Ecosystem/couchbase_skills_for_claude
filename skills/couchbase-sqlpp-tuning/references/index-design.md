# Index design

Choosing the right index type is most of the tuning work. Once the right index exists, the plan usually fixes itself.

## Contents

- [The index types](#the-index-types)
- [Covering indexes](#covering-indexes)
- [Partial indexes](#partial-indexes)
- [Array indexes](#array-indexes)
- [Composite indexes — order matters](#composite-indexes--order-matters)
- [Functional indexes](#functional-indexes)
- [Forcing the optimizer's hand](#forcing-the-optimizers-hand)
- [Vector indexes (8.0+, EE)](#vector-indexes-80-ee)
- [Index Advisor (ADVISE)](#index-advisor-advise)
- [Sizing and lifecycle](#sizing-and-lifecycle)

## The index types

| Type | When to use | Syntax |
|---|---|---|
| **Secondary (GSI)** | Default. Equality or range predicate on one or more fields. | `CREATE INDEX idx ON keyspace(field1, field2);` |
| **Covering** | Hot read query. Avoids the Fetch round-trip. | Same as secondary, but containing every projected and filtered field. |
| **Partial** | Only a fraction of documents are ever queried. | `CREATE INDEX idx ON keyspace(field) WHERE type = 'X';` |
| **Array** | Predicates against array elements (`ANY`, `UNNEST`). `ALL` covers `UNNEST`; `DISTINCT` is smaller and suits `ANY`. | `CREATE INDEX idx ON keyspace(ALL ARRAY v.field FOR v IN arr END);` |
| **Composite** | Multiple equality/range predicates. | `CREATE INDEX idx ON keyspace(f1, f2, f3);` order matters. |
| **Functional** | Predicate on a computed expression. | `CREATE INDEX idx ON keyspace(LOWER(name));` |
| **Primary** | Almost never in production. | `CREATE PRIMARY INDEX ON keyspace;` |
| **Hyperscale vector** (8.0+, EE) | Large-scale vector-only similarity search. | `CREATE VECTOR INDEX idx ON keyspace(embedding VECTOR) WITH {...};` |
| **Composite vector** (8.0+, EE) | Vector search combined with scalar filters. | `CREATE INDEX idx ON keyspace(embedding VECTOR, category) WITH {...};` |
| **Search (FTS)** | Full-text and hybrid search, including Search vector indexes. | Created through the Search Service UI or REST API, not `CREATE INDEX`. |

Index replicas and index partitioning are **Enterprise Edition only**.

## Covering indexes

A covering index contains every field the query touches, so the Query service answers from the index alone with no Fetch.

The recipe:
1. List every field in the SELECT projection
2. List every field in the WHERE clause
3. List every field used in ORDER BY / GROUP BY
4. Create **one** composite index containing all of them, leading with the most selective WHERE field

Query:
```sql
SELECT name, country
FROM `travel-sample`.inventory.hotel
WHERE state = 'CA' AND city = 'Berkeley';
```

Covering index:
```sql
CREATE INDEX idx_state_city_cover
ON `travel-sample`.inventory.hotel(state, city, name, country);
```

The proof is in EXPLAIN: the index-scan operator carries a `covers` list, and there is no `Fetch` operator. `meta().id` is covered implicitly — it appears in the `covers` list without you having to add it as an index key.

Two rules that trip people up:

- **A query cannot be covered by two indexes working together.** It has to be one composite index carrying all the required fields.
- **A partial index can still cover**, but the query has to satisfy the index's WHERE clause, and has to account for keys that evaluate to MISSING.

The trade-off: covering indexes are wider, so they take longer to build, cost more index memory, and slow writes more than a narrow index. Worth it for hot read queries; not worth it for something that runs twice a day.

## Partial indexes

The trap: indexing `docType` — or any low-cardinality field — as the leading key. Every document of that type lands in the index, the optimizer may still pick it, and you get an IntersectScan or a very wide scan.

The fix: make the low-cardinality field a partial-index predicate rather than an index key.

```sql
-- Poor — docType as leading key
CREATE INDEX idx_dtype ON keyspace(docType);

-- Better — docType gates the index; status is the real key
CREATE INDEX idx_user_status
ON keyspace(status)
WHERE docType = 'user';
```

The query must include a predicate that implies the index's WHERE clause for the partial index to qualify:

```sql
SELECT status FROM keyspace
WHERE docType = 'user' AND status = 'active';
```

## Array indexes

Array indexing has rules that bite hard.

### Rule 1: which collection operators can use an array index

This table is the whole game:

| Query operator | Can use an array index | Can be covered |
|---|---|---|
| `ANY ... SATISFIES` | Yes — `DISTINCT ARRAY` or `ALL ARRAY` | Yes, either |
| `UNNEST` | Yes — either, but the array key must be the **leading** index key | `ALL ARRAY` (see below for the `DISTINCT` exception) |
| `ANY AND EVERY` | Yes — either | Yes, either |
| `EVERY` | **No** | No |

`DISTINCT ARRAY` indexes only the unique elements of the array; `ALL ARRAY` indexes every element including duplicates.

**The distinction for `UNNEST` is coverage, not usability — this is widely got wrong.** `UNNEST` does not de-duplicate: it emits one row per array element, duplicates included. A `DISTINCT ARRAY` index has already collapsed duplicates within each document, so it no longer holds enough information to produce those rows. The query still uses the index — the planner selects it and pushes the element predicate down as an exact span — but it wraps the scan in a `DistinctScan` and must **Fetch** each candidate document to re-unnest the array. With `ALL ARRAY` the index entries map one-to-one onto the unnested rows, so the scan can be covered outright, provided every field the query references is in the index.

The aggregation case is the exception worth knowing: where the query itself de-duplicates, a `DISTINCT ARRAY` index can avoid the fetch, because the duplicates it discarded were never going to affect the result.

The documentation's own summary table says "only ALL" for `UNNEST`, but Example 11 on the same page contradicts it: Query B is titled "UNNEST **not covered** when using the DISTINCT index", and the plan it prints shows an `IndexScan3` on that DISTINCT index with `"exact": true` spans. Not covered is not the same as not used. Example 9 Query C goes further, covering an `UNNEST` with a `DISTINCT` index by including the whole array as a second index key.

```sql
-- Serves ANY ... SATISFIES. Also serves UNNEST, but cannot cover it:
-- expect a DistinctScan plus a Fetch.
CREATE INDEX idx_sched_day_distinct
ON route(DISTINCT ARRAY v.day FOR v IN schedule END);

-- Serves both, and can cover UNNEST when the index holds every field
-- the query touches.
CREATE INDEX idx_sched_day_all
ON route(ALL ARRAY v.day FOR v IN schedule END);
```

Pick `DISTINCT ARRAY` when the array holds many repeated values and you only ever use `ANY` — it is smaller and cheaper to maintain. Pick `ALL ARRAY` when you `UNNEST` and want the fetch gone.

### Rule 2: the UNNEST alias does not have to match the index binding

This is a common myth. Since **Couchbase Server 6.5** you can use any alias on the right side of an UNNEST; it does not have to match the binding variable in the array index.

```sql
CREATE INDEX idx_unnest_flight
ON route(ALL ARRAY v.flight FOR v IN schedule END);

-- Both of these can use the index on 6.5+
SELECT r.id FROM route r UNNEST r.schedule v WHERE v.flight LIKE 'UA%';
SELECT r.id FROM route r UNNEST r.schedule s WHERE s.flight LIKE 'UA%';
```

If an UNNEST query isn't using your array index at all, check **leading-key position first** — the array key has to lead. `DISTINCT` versus `ALL` decides whether the scan can be covered, not whether the index is used, so it is the wrong thing to look at when the index is being ignored entirely.

### Rule 3: direct array-element access is not an array predicate

```sql
-- Does not trigger the array index
SELECT * FROM route WHERE schedule[0].day = 2;
```

Rewrite as `ANY v IN schedule SATISFIES v.day = 2 END`.

### Rule 4: composite array indexes mix array keys with scalar keys

```sql
CREATE INDEX idx_country_schedule
ON route(country, ALL ARRAY v.day FOR v IN schedule END);
```

Now `WHERE country = 'US' AND ANY v IN schedule SATISFIES v.day = 2 END` can use the composite array index.

### Rule 5: FLATTEN_KEYS for multiple fields per array element

When you filter on more than one field of the same array element, flatten the keys so the optimizer can treat them as separate index keys:

```sql
CREATE INDEX idx_sched_flat
ON route(DISTINCT ARRAY FLATTEN_KEYS(v.day, v.flight) FOR v IN schedule END);

SELECT r.id FROM route r
WHERE ANY v IN r.schedule SATISFIES v.day = 2 AND v.flight LIKE 'UA%' END;
```

For the index to match, the predicate in the WHERE clause must be sargable for one of the *arguments* of `FLATTEN_KEYS`.

### Rule 6 (7.1+): INCLUDE MISSING on the leading key

If the indexed field can be absent from some documents and you still want those documents indexed:

```sql
CREATE INDEX idx_sched_missing
ON route(ALL ARRAY v.flight FOR v IN schedule END INCLUDE MISSING);
```

`INCLUDE MISSING` applies **only to a leading index key, and only to non-vector fields**. It can also be combined with `FLATTEN_KEYS` to index array elements where the named field is missing.

## Composite indexes — order matters

The leading key must appear in the WHERE clause. The optimizer consumes keys left to right, stopping at the first one not present as a predicate.

```sql
CREATE INDEX idx_abc ON keyspace(a, b, c);

WHERE a = 1                  -- uses idx_abc for 'a'
WHERE a = 1 AND b = 2        -- uses idx_abc for 'a' and 'b'
WHERE a = 1 AND c = 3        -- uses idx_abc for 'a' only; 'c' applied via Filter
WHERE b = 2 AND c = 3        -- idx_abc not selected — no leading key
```

The fix for the last case is a separate index leading with `b`, or a query change that brings `a` into the predicate. Adding `INCLUDE MISSING` to the leading key also lets the index be used when `a` is absent rather than merely unfiltered.

## Functional indexes

If you query on a transformed value, the same transformation has to be in the index:

```sql
SELECT email FROM user WHERE LOWER(email) = 'user@example.com';

CREATE INDEX idx_email_lower ON user(LOWER(email));   -- matches
CREATE INDEX idx_email       ON user(email);          -- does not match the above
```

Indexes on `meta()` fields work the same way — `meta().id`, `meta().cas`, `meta().expiration` and `meta().xattrs` can all be index keys when you actually filter on them.

## Forcing the optimizer's hand

```sql
-- Hint comment (7.6+), preferred
SELECT /*+ INDEX(hotel idx_state_city_cover) */ name, country
FROM `travel-sample`.inventory.hotel AS hotel
WHERE state = 'CA' AND city = 'Berkeley';

-- USE clause, available in earlier releases too
SELECT name, country
FROM `travel-sample`.inventory.hotel USE INDEX (idx_state_city_cover)
WHERE state = 'CA' AND city = 'Berkeley';
```

Neither is a permanent fix — both hardcode an index name. Use one to confirm the right index would help, then work out why the optimizer didn't pick it: usually a competing index with a low-cardinality leading key, a non-sargable predicate, or missing statistics.

## Vector indexes (8.0+, EE)

Couchbase Server 8.0 has three vector index types, all Enterprise Edition (and Capella):

| Type | What it is | Created with |
|---|---|---|
| **Hyperscale vector** | Indexes a single vector column; the fastest option and the lowest memory footprint at very large scale | `CREATE VECTOR INDEX` |
| **Composite vector** | A GSI carrying one vector key plus scalar keys, so scalar filters narrow the set before the vector search | `CREATE INDEX` with a `VECTOR` key |
| **Search vector** | Vector support in the Search Service, for hybrid text + geo + vector queries; documented as suited to roughly 100 million documents | Search Service index definition |

There is **no `USING HYPERSCALE` clause** — the statement you use is what selects the type.

```sql
-- Hyperscale: vector only
CREATE VECTOR INDEX idx_embed_hyperscale
ON product(embedding VECTOR)
WITH {"dimension": 1536, "similarity": "COSINE"};

-- Composite: vector key plus scalar keys for pre-filtering
CREATE INDEX idx_embed_filtered
ON product(embedding VECTOR, category)
WITH {"dimension": 1536, "similarity": "COSINE"};
```

`WITH` options include:

| Option | Meaning |
|---|---|
| `dimension` | Number of dimensions; must match what the embedding model produces |
| `similarity` | `COSINE`, `DOT`, `L2` / `EUCLIDEAN`, `L2_SQUARED` / `EUCLIDEAN_SQUARED`. Default `L2_SQUARED` |
| `description` | Quantization and algorithm settings, matching `^IVF[0-9]*,(SQ[468]\|PQ[0-9]+x[0-9]+)$`; default `IVF,SQ8` |
| `defer_build` | Defer the build; default false |
| `num_replica` | Index replicas (EE); default 1 |
| `scan_nprobes` | Probes per scan; default 1 |
| `train_list` | Training sample size; maximum 1,000,000 |
| `persist_full_vector` | Default true |

Query with `APPROX_VECTOR_DISTANCE()` in the ORDER BY:

```sql
SELECT meta().id, name
FROM product
WHERE category = 'electronics'
ORDER BY APPROX_VECTOR_DISTANCE(embedding, $query_vec, "COSINE")
LIMIT 10;
```

Use `APPROX_VECTOR_DISTANCE()`, not `VECTOR_DISTANCE()`. `VECTOR_DISTANCE()` exists but does **not** use the vector index — it performs a brute-force scan.

Guidance from the docs is to try a Hyperscale index first, and move to Composite only when you need scalar pre-filtering, or to a Search vector index when you need hybrid text/geo/vector queries.

## Index Advisor (ADVISE)

`ADVISE` asks the cluster to recommend indexes for a statement. It is **Enterprise Edition only**.

```sql
ADVISE SELECT name FROM `travel-sample`.inventory.hotel
       WHERE state = 'CA' AND city = 'Berkeley';
```

Syntax is `ADVISE [INDEX] (SELECT | UPDATE | DELETE | MERGE | USING AI)`. The `USING AI` form requires Server 8.0+.

The advice block contains:

| Field | Meaning |
|---|---|
| `current_indexes` | Indexes already available and used for this statement |
| `recommended_indexes` | Indexes to create, or the string "No index recommendation at this time" |
| `covering_indexes` | Recommended covering indexes, when covering would help |

ADVISE optimizes for the single statement you hand it. When several queries could share one wider composite index, design by hand instead. The Index Advisor is also available as a tab in the Query Workbench, and through the MCP `get_index_advisor_recommendations` tool.

Whatever it recommends: rename the index to something meaningful, show the DDL to the user, and get approval before creating it.

## Sizing and lifecycle

Index size depends on the width of the index keys, the number of keys, the number of documents, and the quantization settings for vector indexes — there is no single reliable bytes-per-document number, so measure on your own data rather than guessing. What you can rely on structurally:

- Every extra key in a covering index widens every index entry, so a covering index is always larger and slower to build than the narrow index it replaces
- Every index slows every write to its collection, because each mutation updates each qualifying index
- The Index service has its own memory quota; a cluster that keeps evicting index pages will show high `servTime` on scans
- Index replicas and partitioning cost proportional extra memory (EE)

Check `list_indexes` against the plans you actually see. Indexes that appear in no plan are pure cost — but confirm with the owning team before proposing a drop, since a quarterly job may be the only thing using one.

## What to do next

- Now read the plan → `explain-plan.md`
- Fix the query that triggered the index design → `query-patterns.md`
- Wire this into a workflow → `diagnostic-workflow.md`
- Joins → `joins-and-cbo.md`
