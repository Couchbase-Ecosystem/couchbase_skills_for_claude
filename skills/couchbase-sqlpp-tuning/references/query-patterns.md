# Query patterns and anti-patterns

The most common reasons a Couchbase SQL++ query is slow, and what to do about each. Applies to Couchbase Server 7.x and 8.x; Enterprise-Edition-only features are marked.

## Contents

1. [PrimaryScan / no usable index](#1-primaryscan--no-usable-index)
2. [IntersectScan when a single composite index would work](#2-intersectscan-when-a-single-composite-index-would-work)
3. [Leading key not in WHERE / not sargable](#3-leading-key-not-in-where--not-sargable)
4. [Fetch dominates the runtime](#4-fetch-dominates-the-runtime)
5. [Deep pagination](#5-deep-pagination-limitoffset-at-large-offsets)
6. [OR across different fields](#6-or-across-different-fields)
7. [SELECT *](#7-select-)
8. [Array predicate with EVERY](#8-array-predicate-with-every-no-array-index)
9. [UNNEST not using the array index](#9-unnest-not-using-the-array-index)
10. [Repeated query without PREPARE](#10-repeated-query-without-prepare)
11. [SQL injection through string concatenation](#11-sql-injection-through-string-concatenation)
12. [Wide IN lists](#12-wide-in-lists)
13. [ORDER BY on a non-indexed expression](#13-order-by-on-a-non-indexed-expression)
14. [The "magic" anti-pattern: indexing the docType](#14-the-magic-anti-pattern-indexing-the-doctype)
15. [Filter on a computed field that's expensive](#15-filter-on-a-computed-field-thats-expensive)
16. [Known document keys without USE KEYS](#16-known-document-keys-without-use-keys)

## 1. PrimaryScan / no usable index

Symptom: EXPLAIN shows `PrimaryScan3` or `PrimaryScan`. The query is scanning the entire keyspace.

Causes:
- No secondary index exists that matches the WHERE clause
- An index exists but the leading key isn't in WHERE
- A query field is wrapped in a function call that breaks index matching

Fix: see `index-design.md`. The general rule: build a secondary index whose **leading key matches a field that appears with an equality predicate in WHERE**.

In production, drop the primary index outright once you've confirmed no critical query depends on it. This forces queries to fail loudly instead of silently full-scanning.

Find them with the MCP tool `get_queries_using_primary_index`. Do **not** try to find them by pattern-matching `system:completed_requests` — the `statement` and `preparedText` fields hold the statement text, not the execution plan, so the plan operators never appear there.

Since **7.6**, a query with no usable index may run as an RBAC-controlled *sequential scan* rather than failing, so dropping the primary index no longer guarantees that unindexed queries fail loudly. Check the plans, not just the index list.

## 2. IntersectScan when a single composite index would work

Symptom: EXPLAIN shows `IntersectScan` with two or more child IndexScans.

Cause: Two indexes both qualify for the query, and the optimizer can't tell which is more selective (it's rule-based, no cardinality knowledge), so it runs both and intersects.

Fix: build a single composite index leading with the most-selective predicate.

```sql
-- Before: two single-field indexes
CREATE INDEX idx_state ON hotel(state);
CREATE INDEX idx_city ON hotel(city);
-- Query → IntersectScan(idx_state, idx_city)

-- After: one composite index, most-selective key first
CREATE INDEX idx_city_state ON hotel(city, state);
-- (city is more selective — there are more cities than states)
-- Query → single IndexScan3
```

If the two indexes serve genuinely different queries, leave them. The intersect only happens when both happen to qualify for the same query.

If an intersect scan really is what you want, say so explicitly with the `INDEX_ALL` hint (7.6+) rather than leaving it to chance — it takes two or more index names and performs the intersect across all of them.

## 3. Leading key not in WHERE / not sargable

Symptom: EXPLAIN doesn't pick the index you expect, even though it covers the right fields.

Cause: the leading key of the index is either missing from WHERE entirely, or wrapped in something that makes it non-sargable.

The non-sargable patterns:
| Pattern | Why bad | Fix |
|---|---|---|
| `WHERE field IS NULL` | Index doesn't store NULL by default | Use `INCLUDE MISSING` (7.1+) or restructure |
| `WHERE field IS MISSING` | Same | `INCLUDE MISSING` |
| `WHERE NOT (field = 'x')` | Negation doesn't push down well | Rewrite as `field != 'x'` or, better, broaden the index |
| `WHERE field != 'x'` | Range that excludes one value — sometimes works, often doesn't | Often needs an `INDEX` hint or `USE INDEX` |
| `WHERE LOWER(field) = 'x'` | Function on field breaks index match | Create a functional index on `LOWER(field)` |
| `WHERE field = $1 OR field2 = $2` | OR across fields — usually IntersectScan or UnionScan | Restructure as UNION ALL of two queries, each indexed |

Force selection with the IS NOT MISSING idiom:
```sql
-- If the optimizer won't pick idx_state because 'state' might be missing:
CREATE INDEX idx_state ON hotel(state);

-- Add IS NOT MISSING to make the leading key participate
SELECT * FROM hotel
WHERE state IS NOT MISSING AND state = 'CA';
```

## 4. Fetch dominates the runtime

Symptom: Plan shows a Fetch operator and the profile shows it taking most of the runtime.

Cause: the query isn't covered. Every matching document gets fetched from the Data service.

Fix:
- If the result set is small (< 100 rows) → leave it; one Fetch per row is fine
- If the result set is large → build a covering index that includes every SELECT field
- If you can't cover it (the projection is too wide) → restructure the query to return less, or paginate

Example. Query returns 50,000 rows; runtime 8 seconds; profile shows Fetch taking 7.5s:
```sql
-- Bad — 50,000 fetches
SELECT id, name, address, country
FROM hotel
WHERE state = 'CA';

-- Better — cover it
CREATE INDEX idx_state_cover ON hotel(state, name, address, country);
-- Now: IndexScan3 with covers=[...], no Fetch
```

## 5. Deep pagination (LIMIT/OFFSET at large offsets)

Symptom: `LIMIT 20 OFFSET 100000` is slow. EXPLAIN looks fine but the query takes seconds.

Cause: Couchbase's IndexScan honors LIMIT and OFFSET, but to reach OFFSET 100000 it still has to scan the 100,000 entries in the index — they're just discarded.

Fix: KeySet pagination. Use the last value from page N as the start of page N+1.

```sql
-- Bad — gets worse with depth
SELECT * FROM hotel
WHERE state = 'CA'
ORDER BY name
LIMIT 20 OFFSET 100000;

-- Better — pass the last seen 'name' from the previous page
SELECT * FROM hotel
WHERE state = 'CA' AND name > $last_seen_name
ORDER BY name
LIMIT 20;
```

Constant cost per page, regardless of depth. Trade-off: doesn't support random-access page numbers; only sequential next-page navigation. See `pagination.md` for the full pattern including composite cursors.

## 6. OR across different fields

Symptom: `WHERE a = $1 OR b = $2` is slow.

Cause: a single composite index can't satisfy an OR across different fields with one span. The optimizer's options are a UnionScan or IntersectScan over two indexes, or — if neither index qualifies on its own — an unindexed scan.

Fix: rewrite as UNION ALL with separate, focused indexes:
```sql
-- Bad
SELECT * FROM doc WHERE a = 'foo' OR b = 'bar';

-- Better — two focused queries, each indexed
SELECT * FROM doc WHERE a = 'foo'
UNION ALL
SELECT * FROM doc WHERE b = 'bar' AND (a IS MISSING OR a != 'foo');
```

The `(a IS MISSING OR a != 'foo')` guard prevents duplicates if a doc satisfies both predicates.

## 7. SELECT *

Symptom: queries doing `SELECT *` show large Fetch operators and high network bytes.

Cause: pulls the whole document; can never be covered (the index would have to include every field).

Fix: project only the fields you actually need. This shrinks both Fetch time and network bytes, and it is the precondition for a covering index — you cannot cover a projection you haven't pinned down.

```sql
-- ❌ Pulls the whole doc
SELECT * FROM hotel WHERE state = 'CA';

-- ✓ Project just what you need
SELECT name, country, city FROM hotel WHERE state = 'CA';
```

This is also a precondition for building a covering index — you need to know the exact projection.

## 8. Array predicate with EVERY (no array index)

Symptom: query against an array field doesn't use the array index.

Cause: `EVERY x IN arr SATISFIES ... END` alone is not array-indexable. Only `ANY` and `ANY AND EVERY` are.

Fix: use the right operator.

```sql
-- ❌ EVERY alone — won't use array index
WHERE EVERY v IN schedule SATISFIES v.delayed = false END

-- ✓ Use ANY AND EVERY — uses the array index
WHERE ANY AND EVERY v IN schedule SATISFIES v.delayed = false END
```

Note the semantic difference: `EVERY` evaluates to true on empty arrays, `ANY AND EVERY` requires at least one element. Usually `ANY AND EVERY` is what you want anyway.

## 9. UNNEST not using the array index

Symptom: an `UNNEST` query ignores the array index you built for it, or uses it but still shows a `Fetch` you did not expect.

**Two different problems, and they have different causes.**

*The index is ignored entirely.* The usual cause is leading-key position: for an `UNNEST` scan to use an array index, the array key must be the **leading** index key. `ANY ... SATISFIES` has no such requirement, which is why an index that serves `ANY` can be skipped by `UNNEST`.

*The index is used but the plan still fetches.* That is a `DISTINCT ARRAY` index, and it is working as designed. `UNNEST` does not de-duplicate — it emits one row per element, duplicates included — while a `DISTINCT` index has already collapsed duplicates within each document. It no longer holds what the query needs, so the planner wraps the scan in a `DistinctScan` and fetches each candidate document to re-unnest the array. Switch to `ALL ARRAY` to lose the fetch, provided the index also holds every field the query references.

```sql
-- Serves UNNEST, but cannot cover it: DistinctScan + Fetch
CREATE INDEX idx_unnest_flight_distinct
ON route(DISTINCT ARRAY v.flight FOR v IN schedule END);

-- Serves UNNEST and can cover it
CREATE INDEX idx_unnest_flight_all
ON route(ALL ARRAY v.flight FOR v IN schedule END);

SELECT r.id FROM route r UNNEST r.schedule s WHERE s.flight LIKE 'UA%';
```

Where the query itself aggregates and de-duplicates, a `DISTINCT` index can avoid the fetch after all — the duplicates it dropped could not have changed the answer.

The documentation's summary table on [Array Indexing](https://docs.couchbase.com/server/current/n1ql/n1ql-language-reference/indexing-arrays.html) says `UNNEST` works with "only ALL". Example 11 on that same page shows otherwise — Query B, "UNNEST not covered when using the DISTINCT index", prints a plan with an `IndexScan3` on the DISTINCT index and `"exact": true` spans. Read the table as "ALL is what you want", not as a capability limit.

**Not the cause:** a mismatch between the UNNEST alias and the index's binding variable. Since **Couchbase Server 6.5** the alias can be anything — `s` above works fine against an index defined with `v`. If you have seen advice to rename the alias to match, it predates 6.5.

Other things to check before blaming the index: direct element access (`schedule[0].flight`) is not an array predicate, and filtering on two fields of the same element usually wants `FLATTEN_KEYS`. See `index-design.md`.

## 10. Repeated query without PREPARE

Symptom: A query runs thousands of times per second but each run includes parse + optimize overhead.

Fix: prepare it once, execute many times.

```sql
PREPARE find_hotel_by_state FROM
  SELECT name FROM `travel-sample`.inventory.hotel WHERE state = $state;

-- Named parameters are supplied as an object, not an array
EXECUTE find_hotel_by_state USING {"state": "CA"};
```

SQL++ accepts named (`$state`), numbered (`$1`) and positional (`?`) parameters. There is also an `auto-prepare` query setting that prepares every submitted request automatically; it is **inactive by default**, and it is skipped for parameterised requests that don't use `PREPARE`. Prefer explicit `PREPARE`, or the SDK's `adhoc=False`, over relying on it.

In an SDK:
```python
cluster.query("SELECT name FROM hotel WHERE state = $state",
              QueryOptions(adhoc=False, named_parameters={"state": "CA"}))
```
`adhoc=False` tells the SDK to prepare on first call and cache the prepared name.

Prepared statements also avoid the SQL-injection trap if you bind variables (which you should anyway).

## 11. SQL injection through string concatenation

Symptom (developer-side): queries built by string concat with user input.

Fix: always use named or positional parameters.

```python
# ❌ Injection — also can't be prepared
query = f"SELECT * FROM hotel WHERE city = \"{user_city}\""

# ✓ Parameterized — safe + prepareable
query = "SELECT * FROM hotel WHERE city = $city"
cluster.query(query, named_parameters={"city": user_city})
```

This isn't a "performance" issue strictly, but every preparable query is a covered query opportunity — the security and performance arguments overlap.

## 12. Wide IN lists

Symptom: a query with a large `IN` list falls off a latency cliff. No error, correct results, but `indexScan` and `fetch` phase counts are enormous.

Cause: **spans fanout.** The planner expands `field IN [a, b, c, ...]` — and an `OR` of equality predicates on one field — into one index span per value. There is a ceiling on how many it will generate: **8192 by default, on every shipping version including 8.0.**

Above the ceiling the planner stops enumerating and silently collapses the spans into a single wide range from `ARRAY_MIN(list)` to `ARRAY_MAX(list)`, marked `"exact": false`, re-checking the `IN` after the scan. A wide `OR` collapses to a full index span. You then pay for every index entry and every document between the smallest and largest value in your list. Nothing errors, so this does not show up in logs as a failure.

**How to confirm it.** There is no error code to search for. Turn on request-level debug logging and read the span count:

```sql
\set -loglevel "debug";
SELECT ... FROM ks WHERE c1 > 2 AND c2 IN $list;
```

The response's `log` section reports the count, e.g. `d:'ix1' has 12 Spans`. A count far below your list length means you hit the ceiling. In `EXPLAIN`, the tell is an `IndexScan3` whose `spans` array holds one wide range with `"exact": false` instead of many `low == high` entries.

**Fix the query, in this order:**

1. **If the `IN` list is a list of document keys, use `USE KEYS`** — see anti-pattern 16. This removes the Index Service from the plan entirely and the spans question with it.
2. **If the application already knows the keys, use a KV batch get** from the SDK rather than a query.
3. **Otherwise keep the list under the ceiling** — chunk it and union the results client-side. (Chunking is engineering judgement, not published Couchbase guidance.)

**Do not reach for the feature flag.** The ceiling is raisable through `queryN1QLFeatCtrl`, but Couchbase documents that setting — and its node-level twin `n1ql-feat-ctrl` — with the words "This setting is provided for technical support only", and publishes no meaning for any of its bits. If a workload genuinely needs a larger fanout, that is a Couchbase Support conversation, not a self-service tuning step.

If Support has already prescribed a value, three things matter. It is a **full replacement bitmask, not a value to OR in** — the commonly quoted `33554508` is the documented default `76` plus the fanout bit, so applying it discards any other feature-control customisation on that cluster. The bits are **disable** bits, so setting the fanout bit turns *off* the feature named "Spans Fanout to 8192" and thereby raises the cap. And the resulting cap is version-dependent: **32K on 7.6.6–7.6.7** (MB-64696), **128K on 7.6.8+ and 8.0.0+** (MB-67805). Below 7.6.6 the flag does nothing at all.

## 13. ORDER BY on a non-indexed expression

Symptom: An `Order` operator high in the runtime profile.

Cause: the sort is being done in memory by the Query service because the index can't supply ordered results.

Fix: make sure the ORDER BY fields are at the trailing position of the index in the same direction.

```sql
-- Query
SELECT name FROM hotel WHERE state = 'CA' ORDER BY name;

-- Index that supplies order
CREATE INDEX idx_state_name ON hotel(state, name);
--                                  ^^^^^ ^^^^
--                                  WHERE leading   ORDER trailing
```

The plan should show no separate Order operator — the IndexScan returns rows already sorted.

## 14. The "magic" anti-pattern: indexing the docType

Spotted often: `CREATE INDEX idx_type ON keyspace(docType)`.

Cause: someone added it thinking "we filter on docType everywhere, an index will help." It doesn't. docType has maybe 5-20 distinct values across millions of documents — extremely low cardinality.

Effects:
- Becomes a candidate for IntersectScan with other indexes
- Used as a fallback when no real index qualifies — causes unexpected EXPLAIN plans
- Wastes index memory and write throughput

Fix:
1. Drop `idx_type`
2. Convert every other index to a partial index gated on docType:
```sql
CREATE INDEX idx_user_email
ON keyspace(email)
WHERE docType = 'user';
```

Now `WHERE docType = 'user' AND email = 'x'` uses a tight, partial index. No IntersectScan.

## 15. Filter on a computed field that's expensive

Symptom: `WHERE complex_function(field) = 'x'` is slow.

Cause: the function runs once per document in the Fetch + Filter stages.

Fix:
- Store the computed value at write time as a separate field, index on the stored field
- Or build a functional index on `complex_function(field)` directly

## 16. Known document keys without USE KEYS

Symptom: `WHERE META().id = "..."` or `WHERE META().id IN [...]`, and the plan shows an `IndexScan3`, a `PrimaryScan3`, or — on 7.6+ with no suitable index — a sequential scan.

Cause: filtering on the document key through `WHERE` sends the query to the Index Service to look up keys it was already given.

Fix: use `USE KEYS`. It is not an index hint — it removes the Index Service from the plan altogether, emitting a `KeyScan` that feeds `Fetch` directly, which is as close as SQL++ gets to a KV fetch.

```sql
-- Costs an index round-trip, or a sequential scan if nothing suitable exists
SELECT * FROM hotel WHERE META().id = "hotel_10025";
SELECT * FROM hotel WHERE META().id IN ["hotel_10025", "hotel_10026"];

-- Goes straight to the data service
SELECT * FROM hotel USE KEYS "hotel_10025";
SELECT * FROM hotel USE KEYS ["hotel_10025", "hotel_10026"];
```

Verify with `EXPLAIN`: look for `"#operator": "KeyScan"` and the absence of any scan operator.

Mechanics worth knowing. `USE PRIMARY KEYS` is a synonym. It attaches to a keyspace reference only — never a subquery or expression term (error 4110). It works on `UPDATE` and `DELETE` targets and on a `MERGE` **source**, but not on a `MERGE` target. It composes with `WHERE`, which becomes a post-fetch filter. Keys that do not exist are **not an error**: you get warning 5503, "Key(s) in USE KEYS hint not found", and those rows are simply absent — so a query returning fewer rows than keys supplied is normal. Do not rely on results arriving in the order the keys were listed; add an explicit `ORDER BY` if order matters.

**Ask first whether the query is needed at all.** If the application has the keys and wants whole documents, a KV `get` or batch get through the SDK is one network hop instead of two, and is the recommended path. Reach for `USE KEYS` when you need SQL++ on top of those documents — a join, an aggregate, a projection across many keys, or a transactional `UPDATE`. The one real exception: projecting a few fields from large documents across many keys, where a covering index scan can beat the fetch.

Do not "fix" this by creating an unqualified secondary index on `META().id` — that duplicates the primary index and invites intersect scans. If you genuinely need index access on the key, for a `LIKE 'prefix:%'` scan say, make it a partial index gated on that same predicate.

## What to do next

- Designing the right index from scratch → `index-design.md`
- Reading the EXPLAIN output → `explain-plan.md`
- A specific pagination problem → `pagination.md`
- Joining two keyspaces → `joins-and-cbo.md`
- Step-by-step diagnostic loop → `diagnostic-workflow.md`
