# Diagnostic workflow

How to use the Couchbase MCP server to find, diagnose, and fix slow queries. This is the operational complement to the conceptual references.

## Contents

- [The server and its safety posture](#the-server-and-its-safety-posture)
- [The five-step loop](#the-five-step-loop)
- [Step 1 — Find the slow queries](#step-1--find-the-slow-queries)
- [Step 2 — Understand the plan](#step-2--understand-the-plan)
- [Step 3 — Get an index recommendation](#step-3--get-an-index-recommendation)
- [Step 4 — Propose the index and get approval](#step-4--propose-the-index-and-get-approval)
- [Step 5 — Verify](#step-5--verify)
- [A worked example](#a-worked-example)
- [Querying system:completed_requests directly](#querying-systemcompleted_requests-directly)
- [Schema inference](#schema-inference)
- [Continuous monitoring](#continuous-monitoring)

## The server and its safety posture

The Couchbase MCP server is `couchbase/mcp-server-couchbase`; its documentation lives at https://mcp-server.couchbase.com/. It exposes tools for cluster health, schema discovery, key-value operations, query and indexing, and query-performance analysis.

It runs with `CB_MCP_READ_ONLY_MODE=true` by default. In that mode it prevents data modification for both KV and Query, and the write tools are not loaded at all.

**Treat the cluster as read-only.** Diagnosis needs nothing more. Before any write or DDL — creating an index, dropping an index, `UPDATE STATISTICS`, enabling AUS — show the user the exact statement, state its cost, and get explicit approval. Never flip read-only mode off on your own initiative, and never present index creation as a routine diagnostic step.

Tool names below are current as of this writing; the server's tool list evolves, so verify against the repo README if a call fails.

## The five-step loop

```
1. FIND        →  get_longest_running_queries, get_most_frequent_queries, ...
2. UNDERSTAND  →  explain_sql_plus_plus_query
3. RECOMMEND   →  get_index_advisor_recommendations   (ADVISE; EE only)
4. APPROVE     →  show DDL + cost to the user; wait for an explicit yes
5. VERIFY      →  explain_sql_plus_plus_query, then run with profile=timings
```

## Step 1 — Find the slow queries

A small fraction of queries cause most of the pain. Find them first.

```
Tool: get_longest_running_queries
```
Top queries by elapsed time.

```
Tool: get_most_frequent_queries
```
Top queries by invocation count. Tuning a 0.1s query that runs 100/sec usually beats tuning a 10s query that runs once an hour.

```
Tool: get_queries_using_primary_index
```
Every entry here is doing a full-keyspace scan. High priority.

```
Tool: get_queries_not_using_covering_index
```
Queries doing an index scan plus a Fetch — candidates for promotion to a covering index.

```
Tool: get_queries_not_selective
```
Queries whose WHERE clause doesn't narrow the result set much. Often a wrong index or a missing predicate.

```
Tool: get_queries_with_largest_response_sizes
Tool: get_queries_with_large_result_count
```
Queries moving too much data — often `SELECT *` or a missing LIMIT.

Sort the combined list by **(average duration x frequency)** to get the real priority order.

All of these read `system:completed_requests`, which requires the `query_system_catalog` role, and only contains requests that exceeded the `completed-threshold` setting (1000 ms by default), capped at `completed-limit` most-recent requests (4000 by default). If a query you expect is missing, check those two settings before concluding it's fast.

## Step 2 — Understand the plan

For each query from step 1:

```
Tool: explain_sql_plus_plus_query
Args: {"query": "SELECT name FROM hotel WHERE state = 'CA'"}
```

Read the returned plan as described in `explain-plan.md`. The questions to answer:

- Is the first scan operator a primary scan (or a sequential scan) rather than a secondary index scan?
- Is there an `IntersectScan` where one composite index would do?
- Is there a `Fetch` operator, meaning the query is not covered?
- Are the `spans` on the index scan tight, or wide open?
- Which index did the optimizer actually pick?

Then run the real query with profiling to see where the time actually goes, rather than where you think it goes.

## Step 3 — Get an index recommendation

```
Tool: get_index_advisor_recommendations
Args: {"query": "SELECT name FROM hotel WHERE state = 'CA'"}
```

This runs `ADVISE` against the cluster (Enterprise Edition only). The advice block contains:

- `current_indexes` — indexes already in use for this statement
- `recommended_indexes` — what to create, or the string "No index recommendation at this time"
- `covering_indexes` — recommended covering indexes, when covering would help

ADVISE is conservative: it recommends the minimum index that would help this one statement. If several queries could share one wider composite index, you will usually do better designing by hand — see `index-design.md`.

If ADVISE recommends nothing, either the query is already served well by an existing index, or it has no indexable pattern at all (for example `SELECT * FROM keyspace` with no WHERE clause).

## Step 4 — Propose the index and get approval

Do not create the index yourself. Present it:

```
Proposed:
  CREATE INDEX idx_state_city_cover
  ON `travel-sample`.inventory.hotel(state, city, name, country);

Cost:
  - Build scans the whole collection; on a large keyspace this takes real time.
    Consider WITH {"defer_build": true} plus a scheduled BUILD INDEX.
  - Adds index memory and slows every write to this collection.
  - On Enterprise Edition, consider num_replica for availability.

Effect:
  - Turns the plan from PrimaryScan + Fetch into a covered index scan.
```

Then wait. If the user approves, either they run it themselves (through the Query Workbench, `cbq`, or an SDK), or they explicitly enable write mode on the MCP server and you run it via `run_sql_plus_plus_query`. Many teams keep the MCP server read-only permanently and do all DDL out of band — that is a perfectly good posture; don't argue them out of it.

## Step 5 — Verify

Re-run EXPLAIN on the same statement and confirm:

- the new index name appears as the scan's `index`
- there is no primary scan
- there is no `IntersectScan`
- there is no `Fetch`, if you built a covering index

Then run the query itself with `profile` set to `timings` and compare `kernTime` / `servTime` / `execTime` per operator against the baseline you captured in step 1. A lower total that just moves time from one operator to another is not a win.

## A worked example

User reports: "The hotel-search page is slow."

```
1. get_longest_running_queries
   → Top result: SELECT name, country FROM hotel WHERE state = $1 AND city = $2
                 ~1.8s average, called constantly

2. explain_sql_plus_plus_query
   → Plan: primary scan → Fetch → Filter → InitialProject
   → No secondary index is being used at all

3. get_index_advisor_recommendations
   → recommended_indexes:  CREATE INDEX adv_state_city ON hotel(state, city)
   → covering_indexes:     CREATE INDEX adv_state_city_cover
                             ON hotel(state, city, name, country)

4. Present both to the user. Recommend the covering variant because the query
   is hot and the projection is only two extra fields. Wait for approval.
   The user creates it.

5. explain_sql_plus_plus_query (same statement)
   → Index scan on adv_state_city_cover, covers list includes
     state, city, name, country and meta().id; no Fetch operator.
   Re-run with profile=timings and compare to the baseline.
```

Then move to the next query in the priority list.

## Querying system:completed_requests directly

The pre-canned performance tools cover the common questions. For anything else, query the catalog yourself through `run_sql_plus_plus_query` — reads against system catalogs are allowed in read-only mode.

Useful fields include `statement`, `statementType`, `preparedText`, `requestTime`, `elapsedTime`, `serviceTime`, `executionTime`, `cpuTime`, `resultCount`, `resultSize`, `usedMemory`, `errorCount`, `errors`, `state`, `node`, `users`, `queryContext`, `scanConsistency`, `useCBO`, and the `phaseTimes` / `phaseCounts` / `phaseOperators` objects.

Attribute expensive queries to accounts with the `users` field:

```sql
SELECT users, COUNT(*) AS n, AVG(STR_TO_DURATION(elapsedTime)) AS avg_elapsed
FROM system:completed_requests
GROUP BY users
ORDER BY avg_elapsed DESC;
```

Find statements that mention a keyspace you want to retire:

```sql
SELECT statement, COUNT(*) AS hits
FROM system:completed_requests
WHERE statement LIKE '%old_collection%'
GROUP BY statement
ORDER BY hits DESC;
```

Note the limits of this catalog: `statement` and `preparedText` hold the **statement text**, not the execution plan. You cannot find "queries that used index X" by pattern-matching these fields — the plan is not stored there. Use `get_queries_using_primary_index` and `get_queries_not_using_covering_index` for plan-shaped questions, or EXPLAIN the candidate statements one at a time.

`useCBO` tells you whether the cost-based optimizer ran for that request, which is the quickest way to confirm a CBO problem is really a statistics problem.

## Schema inference

Documents are not schema-enforced, so the shape has to be discovered before you can design an index against it.

```
Tool: get_schema_for_collection
Args: {"bucket_name": "travel-sample",
       "scope_name": "inventory",
       "collection_name": "hotel"}
```

Returns the union of field names and types found in the sampled documents. Use it to confirm field names and, just as importantly, field **types** before writing `CREATE INDEX`: a typo produces a silently empty index, and a field that is sometimes a number and sometimes a string produces an index that only matches half the documents.

## Continuous monitoring

A useful weekly review:

1. `get_longest_running_queries` — has anything new regressed in?
2. `get_queries_using_primary_index` — should be empty in production
3. `get_queries_not_using_covering_index` — promote the hot ones to covering indexes
4. `list_indexes` — look for indexes that appear in no plan; each one costs memory and write throughput. Confirm with the team before proposing any drop.
5. On 8.0+ EE, check that AUS is enabled and its schedule actually ran; on 7.x, confirm the `UPDATE STATISTICS` job is still running.

## What to do next

- Don't know what plan you're looking at → `explain-plan.md`
- Don't know what index to recommend → `index-design.md`
- Don't know what's wrong with the query → `query-patterns.md`
- CBO, hints, or statistics question → `cost-based-optimizer.md`
- Join-specific question → `joins-and-cbo.md`
- Pagination-specific question → `pagination.md`
