# Diagnostics — query performance, plans, and indexes

Answering "what is slow?" and "what should I index?" with the official Couchbase MCP server. Everything in the performance family is read-only; the index-creation tools are writes and are gated accordingly.

## Contents

- [Where to start](#where-to-start)
- [Cluster reachability](#cluster-reachability)
- [The query performance family](#the-query-performance-family)
- [EXPLAIN and plan evaluation](#explain-and-plan-evaluation)
- [The Index Advisor](#the-index-advisor)
- [Listing indexes](#listing-indexes)
- [Creating an index](#creating-an-index)
- [A full investigation](#a-full-investigation)
- [What this server cannot diagnose](#what-this-server-cannot-diagnose)
- [Decision tree](#decision-tree)

## Where to start

Match the question to the entry point:

| The user says | Start with |
|---|---|
| "Couchbase is slow" / "the app is slow" | the query performance family — find the worst offenders first |
| "*this* query is slow" | `explain_sql_plus_plus_query` on that statement |
| "what indexes should I have?" | `get_index_advisor_recommendations` on representative queries |
| "what indexes *do* I have?" | `list_indexes` |
| "is the cluster even up?" | `get_cluster_diagnostics_report`, then `get_cluster_health_and_services` |
| "what is in this collection?" | `get_schema_for_collection` (see `data-plane.md`) |

## Cluster reachability

Two tools, deliberately different in cost.

**`get_cluster_diagnostics_report`** — the SDK's own cached connection state. **Makes no request to the server at all.** For each known endpoint it reports the service, remote and local addresses, connection state, and `last_activity` — how long since that connection saw traffic — plus an overall `online`/`degraded`/`offline` state. Because it performs no I/O it needs no RBAC role beyond whatever the initial connection required, and it is cheap enough to call freely.

Its limit follows directly: it is only as fresh as the last time the SDK talked to each node. A service that just went down, with nothing having touched it since, will still look fine.

**`get_cluster_health_and_services`** — actively pings services and reports, per service, whether it responded, how long it took, which endpoint answered, and any error. This is the live right-now answer, and it is somewhat invasive: a real network round-trip to every targeted service.

- `service_types` narrows the ping. Valid values: `key_value`, `query`, `search`, `analytics`, `view`, `management`, `eventing`. Use it rather than pinging everything by reflex.
- `bucket_name` changes the vantage point. Omitted, the ping is cluster-level — broader coverage in one call, but whether the KV service is included depends on the Couchbase Server version and it may be silently skipped. Supplied, the ping runs from that bucket's perspective, which **guarantees KV coverage for that bucket** but only that bucket. On a multi-bucket cluster, ping per bucket.

Reach for the diagnostics report first. Escalate to the active ping when you need to confirm something is genuinely reachable now.

## The query performance family

Seven read-only tools, each returning the top N queries along one dimension. All take `limit` (default 10).

| Tool | Ranks queries by |
|---|---|
| `get_longest_running_queries` | Average service time |
| `get_most_frequent_queries` | Execution count |
| `get_queries_with_largest_response_sizes` | Result payload size |
| `get_queries_with_large_result_count` | Number of rows returned |
| `get_queries_using_primary_index` | Use of a primary index — usually a missing-secondary-index smell |
| `get_queries_not_using_covering_index` | Fetching documents because the index did not cover the query |
| `get_queries_not_selective` | Index scans returning far more documents than the final result |

These read the Query Service's record of completed requests, so coverage is whatever that service has logged — slow, long-running and failed queries are typically present; trivial sub-second queries may never appear. An empty result does not prove there is no problem; it may mean nothing crossed the logging threshold.

**Read the first two together.** "Slowest" and "most frequent" answer different questions, and the expensive query is often neither on its own: a statement running 10,000 times at 50 ms costs far more total time than one 30-second outlier. Pull both lists and look for statements near the top of each.

The last three are the diagnostic ones — they name a *cause*, not just a symptom. A query on the `using_primary_index` list has no useful secondary index. One on `not_using_covering_index` has an index that could probably be widened to cover it. One on `not_selective` is scanning far more than it returns, which usually means the wrong leading index key or a predicate the index cannot apply.

## EXPLAIN and plan evaluation

`explain_sql_plus_plus_query(bucket_name, scope_name, query)` prefixes `EXPLAIN` if the statement lacks it, then returns:

```json
{
  "query": "...",
  "explain_statement": "EXPLAIN ...",
  "query_context": {"bucket_name": "...", "scope_name": "..."},
  "plan": { ... },
  "plan_evaluation": { ... }
}
```

**Read `plan_evaluation` first.** It is the server's own assessment of the plan — findings already extracted. Only drop into the raw `plan` tree when the evaluation does not explain what you are seeing.

When reading the plan directly, the operators that matter:

- **`PrimaryScan`** — the query is scanning the primary index. On anything but a tiny collection this is the answer to "why is it slow".
- **`IndexScan`** with an `index` name — a secondary index is being used. Check it is the one you expect.
- **`Fetch` after an `IndexScan`** — the index is not covering, so documents are being pulled from the Data Service. Widening the index to include the projected fields removes the fetch.
- **`Order`/sort not backed by an index** — the result set is being sorted in memory.
- **A join between large collections with no index on the join key** — usually the single largest win available.

EXPLAIN does not execute the statement, so it is safe on production and safe under read-only mode.

## The Index Advisor

`get_index_advisor_recommendations(bucket_name, scope_name, query)` runs Couchbase's Index Advisor against a statement. It accepts SELECT, UPDATE, DELETE and MERGE queries. The statement is advised in the given scope, so bare collection names are correct.

The result has three parts:

- `current_used_indexes` — indexes the query already uses
- `recommended_indexes` — suggested secondary indexes
- `recommended_covering_indexes` — suggested covering indexes

Each entry carries the `CREATE INDEX` statement plus the statements that motivated it and their run counts.

**Treat the output as candidates, not commands.** The advisor reasons about one statement's predicates, projection and existing indexes. It does not weigh:

- How often that query actually runs
- Write amplification — every index is maintained on every mutation to the collection
- Disk and Index Service memory cost
- Whether an existing index is nearly the right shape and could be extended instead of duplicated
- Interaction with the rest of the workload

Before recommending any suggestion, check it against `list_indexes`, check the collection's size and write rate, and prefer widening an existing index over adding a near-duplicate.

## Listing indexes

`list_indexes` accepts hierarchical filters — `bucket_name`, then `scope_name`, then `collection_name`, then `index_name`; each level requires the ones above it. `return_raw_index_stats=true` returns the unprocessed source row.

Each entry gives `name`, `definition` (the `CREATE INDEX` statement), `status`, `isPrimary`, `bucket`, `scope`, `collection` and `lastScanTime`. Where a required field is missing, the entry carries a warning and the raw stats instead.

**`lastScanTime` is the unused-index signal.** An index that has not been scanned in a long time is costing writes and memory for nothing — worth raising, though never dropping without the user's decision.

**The source differs by version.** On **8.0+** clusters this reads `system:indexes` through the Query Service, which is RBAC-scoped: the connected user sees only indexes on keyspaces they can access. On **7.x** it falls back to the admin-level Index Service REST API. So on 8.0+ an index can be genuinely absent from the listing simply because the MCP user cannot see that keyspace — check the user's roles before concluding an index does not exist.

## Creating an index

`create_index`, `build_index` and `drop_index` are **write** tools, absent under the default read-only mode. Read `safety.md` before composing any of them.

`create_index(bucket_name, scope_name, collection_name, index_name, keys, deferred=True, condition, num_replicas, ignore_if_exists)` creates a scalar (non-vector) GSI secondary index. It cannot create vector indexes.

- `keys` — fields or expressions, e.g. `["email"]` or `["type", "created_at DESC"]`
- `condition` — an optional WHERE clause for a partial index, e.g. `type = 'user'`
- `num_replicas` — index replicas for availability and scaling
- `ignore_if_exists` — avoid an error when the name is taken

Prefer this tool over a raw `CREATE INDEX` through `run_sql_plus_plus_query`: it defers the build by default and reports the recommended next step.

The sequence is **create → build → verify**:

1. `create_index` for each index, deferred (the default). Deferring lets several indexes build together in one pass rather than scanning the collection repeatedly.
2. `build_index` once, to trigger the build of all deferred indexes on the collection.
3. `list_indexes` to confirm each reaches `online`. An index is not usable until then — do not tell the user a query is fixed before you have checked.

## A full investigation

A typical "the database is slow" walk:

1. `get_cluster_diagnostics_report` — rule out a connectivity or node problem before chasing queries.
2. `get_most_frequent_queries` and `get_longest_running_queries` — build the candidate list. Weigh frequency against duration.
3. `get_queries_using_primary_index` and `get_queries_not_using_covering_index` — these name causes directly and often overlap the candidate list.
4. For each real suspect, `explain_sql_plus_plus_query` — confirm the mechanism rather than assuming it.
5. `get_index_advisor_recommendations` on the confirmed offenders — collect candidate DDL.
6. `list_indexes` on the affected collections — check for an existing index to extend, and for near-duplicates.
7. Present the recommendation with its cost. Only then, with explicit approval and writes enabled: `create_index` (deferred) → `build_index` → `list_indexes` to confirm `online`.

Steps 1–6 are entirely read-only and safe on production.

## What this server cannot diagnose

The performance tools are query-level. They say nothing about node CPU or memory, Data Service resident ratio, disk queues, index memory pressure, rebalance progress, XDCR lag, or Eventing failures. Those live in the Couchbase Web Console's statistics and monitoring, the Management REST API, `couchbase-cli`, or the cluster's own metrics pipeline — not in this server. Say so and point there rather than approximating with query statistics.

Cluster-wide monitoring and alerting design is a separate concern; the `couchbase-performance-tuning` and `couchbase-observability` skills cover it.

## Decision tree

- **"Everything is slow"** → diagnostics report, then frequency + duration lists together
- **"This query is slow"** → `explain_sql_plus_plus_query`, read `plan_evaluation` first
- **Plan shows a primary scan** → `get_index_advisor_recommendations`, then check `list_indexes` for something to extend
- **Plan shows a fetch after an index scan** → widen the existing index to cover, rather than adding a new one
- **"What should I index?"** → advisor on representative queries, filtered through run frequency and write cost
- **"Do we have unused indexes?"** → `list_indexes`, look at `lastScanTime`
- **"Is the cluster reachable?"** → `get_cluster_diagnostics_report` first; `get_cluster_health_and_services` with `service_types` if you need a live probe
- **Node, memory, disk, replication or rebalance questions** → not this server; Web Console, `couchbase-cli`, or the Management REST API
