# SQL++ in application code

How to write SQL++ (N1QL) safely from application code. This is the *safety-in-code* companion to the `couchbase-sqlpp-tuning` skill (which covers query *performance* — indexes, EXPLAIN, the optimizer). Here the concern is injection, correctness, and result handling.

> **Verify option symbols against the pinned SDK.** `QueryOptions`, parameter-passing, and scan-consistency enums are shown in current Python SDK 4.x form, taken from the SDK's own docs; confirm against the project's SDK and version. Other SDKs use different spellings for the same concepts.

## Contents

- [Always parameterize](#always-parameterize--never-concatenate)
- [Named vs positional](#named-vs-positional-parameters)
- [Scan consistency](#scan-consistency)
- [Result handling](#result-handling)
- [Pagination](#pagination)
- [Query hygiene](#query-hygiene)
- [Checklist](#checklist)

## Always parameterize — never concatenate

**Building a SQL++ string from user input is an injection vulnerability, full stop.** It's the SQL-injection class of bug, and it applies to SQL++ exactly as to SQL.

```python
# WRONG — injection. `city` from a request could be:  x" OR 1=1 OR "
q = f'SELECT * FROM `travel-sample` WHERE type="airport" AND city="{city}"'
cluster.query(q)

# RIGHT — parameterized; the value can never break out of its slot
q = 'SELECT * FROM `travel-sample` WHERE type = "airport" AND city = $city'
cluster.query(q, QueryOptions(named_parameters={"city": city}))
```

- **Every value that comes from outside the code is a parameter, never string-interpolated.** User input, request fields, values read from other systems — all parameterized.
- **This is a blocking review defect, not a style preference.** String-built SQL++ from external input fails review.
- **Identifiers can't always be parameterized** (bucket/scope/collection/field names aren't bindable as parameters in most engines). When those must be dynamic, validate them against a strict allow-list of known-good names — never pass user input straight into an identifier position.

## Named vs positional parameters

Both are safe; pick for readability:

```python
# Named — self-documenting, order-independent, preferred for multi-param queries
cluster.query(
    "SELECT ts.* FROM `travel-sample`.inventory.airport WHERE city = $city AND country = $country",
    QueryOptions(named_parameters={"city": city, "country": country}),
)

# Positional — terse, fine for one or two params
cluster.query(
    'SELECT VALUE name FROM `travel-sample` WHERE type = "airline" AND callsign = $1',
    QueryOptions(positional_parameters=[call_sign]),
)
```

Both forms are documented: named parameters use `$name` in the statement with a `named_parameters` mapping; positional parameters use `$1`, `$2`, … with a `positional_parameters` sequence ([SQL++ from the Python SDK](https://docs.couchbase.com/python-sdk/current/howtos/n1ql-queries-with-sdk.html)).

Prefer **named** parameters once there's more than one — positional args drift out of sync with the query text as it's edited. The SDK docs also note that parameters cannot be used in every position within a statement; identifiers in particular are not bindable (see the allow-list rule above).

## Scan consistency

SQL++ reads a GSI index, which is updated asynchronously after a KV write. This creates a read-your-write hazard: write a document via KV, immediately query for it, and a default query may not see it yet.

- **`NOT_BOUNDED` (default)** — fastest; may not reflect the most recent writes. Fine for dashboards, search, analytics where slight staleness is acceptable.
- **`REQUEST_PLUS`** — the query waits for the index to catch up to the moment of the request, so it sees prior writes. Use when the query must reflect a just-written document (read-after-write in the same flow). Costs latency.
- **"At plus" — `consistent_with` with a `MutationState`** — waits only for the *specific* mutations whose tokens you captured, rather than everything pending. **This is not an enum member**: there is no `QueryScanConsistency.AT_PLUS` in the current SDKs. Reviewers should treat a reference to one as a version smell or a hallucinated symbol.

```python
from couchbase.options import QueryOptions
from couchbase.n1ql import QueryScanConsistency

cluster.query(
    "SELECT * FROM `app`.`_default`.orders WHERE customer = $c",
    QueryOptions(scan_consistency=QueryScanConsistency.REQUEST_PLUS,
                 named_parameters={"c": customer_id}),
)
```

- **Choose consistency deliberately and comment why.** Defaulting to `REQUEST_PLUS` everywhere needlessly slows queries; defaulting to `NOT_BOUNDED` where read-after-write matters is a correctness bug. The choice is a decision the reviewer should be able to see.
- **Better still: if you have the key, don't query at all** — a KV `get` is always read-your-own-write consistent. See `couchbase-sdk-idioms.md`.
- **Validation and reconciliation queries need `REQUEST_PLUS`.** A `SELECT COUNT(*)` run at the default `NOT_BOUNDED` can under-count against an index that hasn't caught up, which reads as a data-loss bug that isn't one. Any query whose *purpose* is to assert a fact about current state must be request-plus.

## Result handling

- **Stream rows; don't materialize huge result sets into memory.** Iterate the result (it's lazy) rather than collecting millions of rows into a list.
- **Don't `SELECT *` when you need three fields.** Project only what you use — less network, less parsing, and it makes the covering-index path possible (see `couchbase-sqlpp-tuning`).
- **Extract metadata when you need it** (metrics, warnings) from the result object — don't discard the result wrapper blindly.

## Pagination

- **Keyset (seek) pagination over `OFFSET` for deep pages.** Large `OFFSET` values make the engine scan and discard everything before the offset — cost grows with page depth. Paginate by a `WHERE key > $last_seen ORDER BY key LIMIT n` seek instead.

```sql
-- deep OFFSET: scans and throws away 10,000 rows every page
SELECT ... ORDER BY created_at LIMIT 20 OFFSET 10000;

-- keyset: consistent cost regardless of depth
SELECT ... WHERE created_at > $last_seen ORDER BY created_at LIMIT 20;
```

## Query hygiene

- **Keep query text readable** — multi-line string, aligned clauses, not a 400-char one-liner. A reviewer has to be able to read it.
- **Reference collections fully and consistently** (`bucket.scope.collection`), matching the key/collection constants from `key-and-document-conventions.md`.
- **Don't hand-build repeated queries by concatenation.** Define the query text once (a constant or a small builder), parameterize the values.
- **Set a query timeout** appropriate to the workload; don't rely on an implicit default for a query that could run long. The Java SDK's documented `queryTimeout` default is 75s — generous for an interactive path and short for a large batch aggregation, so neither should inherit it silently.
- **Prefer scope-level queries** where the statement only touches one scope: issuing `scope.query(...)` lets you write unqualified collection names and routes the request appropriately.
- **Keep statement text stable across calls** so the prepared plan is reusable — vary the bound values, never the string.

## Checklist

- [ ] Every external value is a bound parameter — zero string interpolation of input
- [ ] Dynamic identifiers (if any) validated against an allow-list, never raw input
- [ ] Named parameters for multi-param queries
- [ ] Scan consistency chosen deliberately and commented; `REQUEST_PLUS` only where read-after-write is required
- [ ] KV used instead of query where the key is known
- [ ] Results streamed, not materialized; only needed fields projected
- [ ] Keyset pagination for deep pages, not large `OFFSET`
- [ ] Query text readable; collections fully qualified; timeout set
- [ ] Statement text constant across calls; only bound values vary
- [ ] Any query asserting current state (counts, reconciliation, validation) uses `REQUEST_PLUS`
