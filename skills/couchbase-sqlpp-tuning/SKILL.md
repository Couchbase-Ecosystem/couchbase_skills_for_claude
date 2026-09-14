---
name: couchbase-sqlpp-tuning
description: "Diagnose and tune slow Couchbase SQL++ queries. Use whenever the user asks about query performance, slow queries, EXPLAIN plans, why an index isn't being used, IntersectScan, PrimaryScan, covering indexes, partial indexes, array indexes (ANY / UNNEST / FLATTEN_KEYS), index selection, optimizer hints, the cost-based optimizer, Auto Update Statistics, the Index Advisor (ADVISE), system:completed_requests, query profiling (kernTime / servTime / execTime), pagination performance, prepared statements, or 'this query is slow / how do I make it faster.' Covers Couchbase Server 7.x and 8.x and flags Enterprise-Edition-only features. Distinct from couchbase-data-modeling (document shape) and couchbase-mcp (operating the cluster) — this skill is about reading plans, designing the right indexes, and reshaping queries that already exist. Use proactively when the user shares an EXPLAIN output or a slow query."
license: Apache-2.0
---

# Couchbase SQL++ tuning

A skill for diagnosing and fixing slow SQL++ queries on Couchbase Server (7.x and 8.x, and Capella). The mechanics of reading execution plans, choosing the right index type, fixing common anti-patterns, and wiring up the diagnostic tools. (SQL++ was previously called N1QL; the two names refer to the same language.)

Distinct from the sibling skills:
- `couchbase-data-modeling` — how to MODEL the data (document shape, boundaries, access patterns)
- `couchbase-sizing` — how to size the cluster
- `couchbase-app-integration` — how to write app code that uses Couchbase
- `couchbase-migration-execution` — how to move data INTO Couchbase
- `couchbase-mcp` — operating the cluster
- **`couchbase-sqlpp-tuning` (this skill)** — making queries that already exist run faster

If the conversation is "this query is slow, what do I do," this is the right skill.

## Safety: treat the cluster as read-only

The Couchbase MCP server (`couchbase/mcp-server-couchbase`, docs at https://mcp-server.couchbase.com/) ships with `CB_MCP_READ_ONLY_MODE=true` by default. In that mode it blocks data modification and the write tools are not even loaded.

Keep it that way while diagnosing. **Never create, drop, or alter an index — or run any other DDL or write — without the user explicitly approving that specific statement first.** Present the DDL, say what it will cost (build time, memory, write amplification), and wait for a yes. Index creation on a production cluster is a real operational event, not a diagnostic step.

## When this skill applies

- "Why is this query slow?"
- "How do I read this EXPLAIN plan?"
- "Why isn't my index being used?"
- "I'm seeing PrimaryScan / IntersectScan — is that bad?"
- "How do I make this a covering index?"
- "Should I use a partial index here?"
- "How do I index an array field with ANY / UNNEST?"
- "ADVISE recommended this index — should I create it?"
- "How do I tune pagination — LIMIT / OFFSET is slow at high offsets"
- "What does kernTime / servTime / execTime mean in the profile?"
- "Can I force the optimizer to use a specific index?"
- "What do the optimizer hints do in 7.6+?"

## Core principles (read first)

These are the headline rules. Read them before diving into references.

1. **Pareto applies to query tuning.** 80% of perf problems come from a small fraction of queries. Use `system:completed_requests` (or the MCP `get_longest_running_queries` / `get_most_frequent_queries` tools) to find them first. Don't tune the wrong queries.

2. **CBO needs statistics to help; without them it falls back to rule-based logic.** The cost-based optimizer is **Enterprise Edition only — not available in Community Edition**. In **7.6+** the Query service gathers statistics automatically when an index is created or built. In **8.0+ EE** *Auto Update Statistics* (AUS) can keep them fresh on a schedule, but **AUS is opt-in and disabled by default** — you must enable and schedule it via `system:aus`. Otherwise, refresh statistics with `UPDATE STATISTICS` yourself.

3. **The leading key of the index must appear in the WHERE clause** for that index to be picked. If the field can be absent from some documents, add `INCLUDE MISSING` to the leading key (the clause applies only to a leading, non-vector index key), or add an `IS NOT MISSING` / `IS NOT NULL` predicate.

4. **Cover the query when it's hot.** A covering index contains every field the query projects and filters on, so the query never touches the Data service. Look for `"covers": [...]` on the index-scan operator and the absence of a `Fetch` operator. Note: **a query cannot be covered by two indexes together** — it must be one composite index carrying all the required fields.

5. **Don't index a low-cardinality field like `docType` alone.** It invites IntersectScans and wrong plans. Use it as a partial-index predicate (`WHERE docType = 'X'`) so it gates the index instead of leading it.

6. **Match the query shape to the index shape for arrays.** `ANY ... SATISFIES` works with either `DISTINCT ARRAY` or `ALL ARRAY`. `UNNEST` works with either too, but only `ALL ARRAY` can cover it — a `DISTINCT` index forces a `DistinctScan` plus a Fetch, because `UNNEST` does not de-duplicate and a DISTINCT index has already dropped the duplicates. For `UNNEST` the hard requirement is that the array key leads the index.

7. **Avoid PrimaryScan in production**, but know that dropping the primary index is no longer a hard stop: **7.6+** added RBAC-controlled *sequential scans*, so a query with no usable index can still run by scanning the Data service. Either way, an unindexed scan is a full-keyspace read — find it and index it.

## Pick the right reference

| Question | Read |
|---|---|
| "How do I read this EXPLAIN plan? What's PrimaryScan / IntersectScan / Fetch?" | `references/explain-plan.md` |
| "What kind of index should I create? Covering / partial / array / composite / vector?" | `references/index-design.md` |
| "Why isn't my index being used? Common query anti-patterns and how to fix them" | `references/query-patterns.md` |
| "What does the cost-based optimizer do? What are the hints? What is AUS?" | `references/cost-based-optimizer.md` |
| "How do I wire this up with the Couchbase MCP server tools?" | `references/diagnostic-workflow.md` |
| "How do I do efficient pagination on a large result set?" | `references/pagination.md` |
| "How do I tune queries that join across keyspaces?" | `references/joins-and-cbo.md` |

## Workflow

The general approach to tuning a slow query:

```
1. Identify  →  Find the slow query (Pareto: top by frequency x duration)
                Tools: get_longest_running_queries, get_most_frequent_queries,
                       or system:completed_requests directly

2. Understand →  Run EXPLAIN. Read the plan.
                 Tool: explain_sql_plus_plus_query
                 What to look for: PrimaryScan? IntersectScan? Fetch present?
                                   Is the leading key of an index in WHERE?

3. Hypothesize → Pick one of:
                 - Add a covering index (everything in one index, no Fetch)
                 - Add a partial index (smaller, indexed on a subset)
                 - Add an array index (ALL / DISTINCT ARRAY, or FLATTEN_KEYS)
                 - Reshape the query (split OR predicates, add IS NOT MISSING)
                 - Add an INDEX hint
                 Tool: get_index_advisor_recommendations (ADVISE)

4. Approve    → Show the user the exact DDL and its cost. Wait for explicit
                approval. Do not create indexes on your own initiative.

5. Verify     → Re-run EXPLAIN. Check the new index is picked.
                Run the query with profile=timings; read kernTime / servTime /
                execTime per operator.

6. Iterate    → Repeat until the query meets SLA, or further tuning has
                diminishing returns.
```

## Anti-pattern checklist

Quick scan list — if you see any of these, jump to `references/query-patterns.md`:

- `SELECT *` from a large keyspace (forces Fetch, can't be covered)
- `WHERE docType = 'X'` as the leading filter (low-cardinality leading key)
- `WHERE NOT (...)`, `!=`, `NOT IN` predicates (often not sargable)
- `OR` across different fields (often forces IntersectScan / UnionScan, or no index at all)
- `EVERY x IN arr SATISFIES ... END` (no array-index support — use `ANY` or `ANY AND EVERY`)
- `UNNEST` against a `DISTINCT ARRAY` index — it works, but never covers; expect a Fetch
- `LIMIT 10 OFFSET 1000000` (deep pagination — use keyset pagination)
- Raw user input concatenated into the statement (injection, and it can't be prepared)
- A query that runs thousands of times per second with no `PREPARE`

## Tooling

The Couchbase MCP server (`couchbase/mcp-server-couchbase`) exposes the tuning tools you need. Verify the current list against the repo README — it evolves.

| Tool | Purpose |
|---|---|
| `explain_sql_plus_plus_query` | Run EXPLAIN on a statement |
| `run_sql_plus_plus_query` | Run a SQL++ statement (writes/DDL blocked in read-only mode) |
| `get_index_advisor_recommendations` | ADVISE; recommends indexes (EE only) |
| `list_indexes` | Indexes that currently exist |
| `get_longest_running_queries` | Top N queries by duration |
| `get_most_frequent_queries` | Top N queries by frequency |
| `get_queries_with_largest_response_sizes` | Queries returning the most bytes |
| `get_queries_with_large_result_count` | Queries returning the most rows |
| `get_queries_using_primary_index` | Queries hitting the primary index (bad in prod) |
| `get_queries_not_using_covering_index` | Queries that could be covered but aren't |
| `get_queries_not_selective` | Queries where the WHERE filter doesn't narrow much |
| `get_schema_for_collection` | Sample document schema (for designing the right index) |
| `get_cluster_health_and_services` | Which services and nodes are present |

The performance tools read `system:completed_requests`, which requires the `query_system_catalog` role. Query monitoring and profiling are listed as Enterprise Edition features on the Couchbase editions comparison — on Community Edition, plan on EXPLAIN plus application-side timing instead.

See `references/diagnostic-workflow.md` for the full step-by-step.

## Version notes

Gate every recommendation on the cluster's actual version and edition.

- **Pre-7.0:** No scopes/collections — indexes are bucket-level
- **6.5:** UNNEST alias no longer has to match the array index's binding variable; cost-based optimizer available as a developer preview
- **7.0:** Scopes and collections; covering, partial, array and composite indexes on collections
- **7.1+:** `INCLUDE MISSING` on a leading index key, so documents missing that field are still indexed
- **7.6+:** Query service gathers CBO statistics automatically on index create/build; RBAC-controlled sequential scans (query without an index); `/*+ ... */` and `--+` optimizer hints (`INDEX`, `INDEX_ALL`, `INDEX_FTS`, `USE_NL`, `USE_HASH`, `ORDERED`); Vector Search via the Search Service
- **8.0+:** Hyperscale, Composite and Search vector indexes (EE); `APPROX_VECTOR_DISTANCE()`; Auto Update Statistics (EE, opt-in, off by default); `ADVISE ... USING AI`; XDCR conflict logging; new buckets default to Magma with 128 vBuckets
- **Enterprise Edition only (not in Community Edition):** cost-based optimizer, AUS, `UPDATE STATISTICS`, ADVISE, hash joins (`USE_HASH` is silently ignored in CE), index replicas and partitioning, vector indexes, Magma, Analytics

Confirm the version and edition before recommending a feature — `get_cluster_health_and_services` reports what the server is running.

## Related skills

- `couchbase-data-modeling` — when the real fix is the document shape, not another index
- `couchbase-app-integration` — client-side scan consistency, timeouts and prepared statements
- `couchbase-performance-tuning` — cluster- and service-level tuning beyond a single query
- `couchbase-fts` — when the right access path is a Search index rather than a GSI
- `couchbase-coding-standards` — query safety in application code (parameterization, injection hygiene)
- `cb-analytics-query` — applying these tuning principles to Analytics SQL++ through cb-analytics-mcp
- `couchbase-ai-applications` — end-to-end RAG design behind `APPROX_VECTOR_DISTANCE()` queries and vector index choice
- `couchbase-columnar` — Capella Analytics and Enterprise Analytics, where analytical SQL++ has its own dialect and plans
- `couchbase-mcp` — running EXPLAIN, the Index Advisor and completed-requests diagnostics over MCP
