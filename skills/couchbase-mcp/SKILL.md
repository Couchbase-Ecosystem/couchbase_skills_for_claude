---
name: couchbase-mcp
description: "Operates a Couchbase cluster through the official Couchbase MCP server (couchbase/mcp-server-couchbase, PyPI couchbase-mcp-server, run with uvx). Covers its 37 data-plane tools: cluster health and SDK diagnostics, bucket/scope/collection discovery, schema inference, key-value and sub-document operations, SQL++ query and EXPLAIN, GSI index listing plus the Index Advisor, Search (FTS) index listing and queries, and query-performance analysis. Use when the user mentions the Couchbase MCP server, uvx couchbase-mcp-server, CB_CONNECTION_STRING, CB_MCP_READ_ONLY_MODE, MCP tools for Couchbase, or asks to list buckets, scopes or collections, run SQL++ or N1QL, read or write documents, run a Search query, diagnose slow queries, or find missing indexes over MCP. Distinct from couchbase-admin-mcp, which covers cluster administration through a separate admin MCP server, and from skills that tune Couchbase itself rather than drive it over MCP."
license: Apache-2.0
---

# Couchbase MCP

Drives a Couchbase cluster — Capella or self-managed — through the **official Couchbase MCP server**, `couchbase/mcp-server-couchbase`. That server is the only one this skill documents.

- **Repo**: https://github.com/couchbase/mcp-server-couchbase (Apache-2.0)
- **Docs**: https://mcp-server.couchbase.com/ and https://docs.couchbase.com/mcp-server/get-started/overview.html
- **Distribution**: PyPI `couchbase-mcp-server` (`uvx couchbase-mcp-server`), Docker `docker.io/couchbase/mcp-server`. Python 3.10+. **No npx/Node build exists** — if a config uses `npx`, it is wrong.
- **Registry identity**: `io.github.couchbase/mcp-server-couchbase`
- **Support**: Couchbase community-maintained, not covered by the Couchbase support team. Enterprise support is available by licensing Couchbase AI Data Plane. Raise issues on the GitHub repo.

`Couchbase-Ecosystem/mcp-server-couchbase` is a stale mirror; its own `server.json` points at the canonical repo above. Prefer the canonical repo for issues, releases, and source.

## What this server does and does not do

It is a **data-plane** server. It reads and (when writes are enabled) modifies data, schema containers, and GSI indexes inside a cluster you are already connected to.

It has **no cluster administration and no Capella control-plane tools**. There is nothing here for bucket creation, users and RBAC, rebalance, failover, XDCR, Eventing, backup/restore, encryption/KMIP, audit, or Capella organizations, projects and allowlists. When a task needs one of those, say so in one line and route the user to the right surface:

| Task | Where it belongs |
|---|---|
| Buckets, users/RBAC, rebalance, failover, XDCR, Eventing, backup, audit, encryption | Couchbase Web Console, `couchbase-cli`, or the Management REST API |
| Capella organizations, projects, clusters, database users, allowed CIDRs, app services | Capella UI or the Capella Management API v4 |
| The same admin surface driven over MCP | the `couchbase-admin-mcp` skill |

Do not invent tool names for these. If a capability is not in `references/tool-index.md`, this server does not have it.

## Read-only by default — the posture for every session

`CB_MCP_READ_ONLY_MODE` defaults to **`true`**. In that mode the 12 write tools are **not loaded at all** (they never appear in tool discovery) and SQL++ statements that modify data, structure, or privileges are blocked at runtime. Only the 25 read-only tools are available.

Treat the cluster as read-only regardless of how the server is configured:

1. Assume reads are fine and writes are not.
2. Before any write, DDL, or delete — even when the write tools are present — describe the target and the blast radius, then get explicit user approval. Never infer approval from an earlier "go ahead".
3. If a write tool is missing, that is the server's configuration working as intended. Say so and offer the read-only path; never suggest flipping `CB_MCP_READ_ONLY_MODE=false` as a casual fix.
4. Tool gating guides model behaviour. The connected Couchbase user's **RBAC is the real security boundary** — a narrow role is worth more than a disabled tool.

Full treatment in `references/safety.md`.

## Pick the right reference

Read the one that matches the task. They are self-contained; do not read them all up front.

| Task | Read |
|---|---|
| Installing, connecting, transports, env vars, client config, Docker, OAuth, logging | `references/configuration.md` |
| KV reads/writes, sub-document ops, SQL++, EXPLAIN, schema inference, Search (FTS) queries | `references/data-plane.md` |
| Slow queries, index advisor, plan evaluation, "what should I index?" | `references/diagnostics.md` |
| Anything that writes, drops, or deletes — read BEFORE composing the call | `references/safety.md` |
| RBAC for the MCP user, mTLS, OAuth scopes, transport hardening, tool disabling | `references/security-best-practices.md` |
| "What is the exact tool name for X?" | `references/tool-index.md` |
| Errors: connection, auth, query, index, FTS, tool-not-found | `references/troubleshooting.md` |

## Tool surface at a glance

37 tools — **25 read-only** (always loaded) and **12 write** (loaded only when `CB_MCP_READ_ONLY_MODE=false`).

| Category | Read-only | Write |
|---|---|---|
| Cluster & server | `get_server_configuration_status`, `test_cluster_connection`, `get_cluster_health_and_services`, `get_cluster_diagnostics_report` | — |
| Schema discovery | `get_buckets_in_cluster`, `get_scopes_in_bucket`, `get_collections_in_scope`, `get_scopes_and_collections_in_bucket`, `get_schema_for_collection` | `create_scope`, `create_collection`, `delete_scope`, `delete_collection` |
| Key-value | `get_document_by_id`, `lookup_subdocument` | `upsert_document_by_id`, `insert_document_by_id`, `replace_document_by_id`, `delete_document_by_id`, `mutate_subdocument` |
| Query & index | `run_sql_plus_plus_query`, `explain_sql_plus_plus_query`, `list_indexes`, `get_index_advisor_recommendations` | `create_index`, `build_index`, `drop_index` |
| Search (FTS) | `list_fts_indexes`, `get_fts_index_definition`, `run_fts_query` | — |
| Query performance | `get_longest_running_queries`, `get_most_frequent_queries`, `get_queries_with_largest_response_sizes`, `get_queries_with_large_result_count`, `get_queries_using_primary_index`, `get_queries_not_using_covering_index`, `get_queries_not_selective` | — |

Version gates: scope/collection management tools apply to **Couchbase Server 7.6+ and Capella**. The Search (FTS) tools require **7.6+** and the Search Service. `list_indexes` reads `system:indexes` through the Query Service on **8.0+** clusters (results are RBAC-scoped to the connected user) and falls back to the Index Service REST API on **7.x**.

## Calling conventions

**Everything is keyspace-addressed explicitly.** Nearly every data tool takes `bucket_name`, `scope_name`, and `collection_name` as arguments — there are no ambient `CB_BUCKET`/`CB_SCOPE` defaults to fall back on. Discover the keyspace before you use it: `get_buckets_in_cluster` → `get_scopes_and_collections_in_bucket`.

**SQL++ runs inside a scope.** `run_sql_plus_plus_query(bucket_name, scope_name, query)` sets the query context for you, so write bare collection names:

```
SELECT * FROM users WHERE status = 'active' LIMIT 10     -- correct
SELECT * FROM travel.inventory.users WHERE ...           -- wrong, double-qualified
```

**Bind parameters, never concatenate.** Pass user-supplied values through `named_parameters` against `$name` placeholders. String-concatenating input into a statement is a SQL++ injection path.

```json
{"bucket_name": "travel-sample", "scope_name": "inventory",
 "query": "SELECT name FROM airline WHERE country = $country LIMIT 10",
 "named_parameters": {"country": "United States"}}
```

**Prefer the purpose-built tool over raw SQL++.** `create_index` over `CREATE INDEX`, `run_fts_query` over SQL++ `SEARCH()`, `get_schema_for_collection` over `SELECT * LIMIT 5`, `list_indexes` over querying `system:indexes`. The dedicated tools return better-shaped results and carry the right guardrails.

**Do not guess field paths.** `lookup_subdocument` and `mutate_subdocument` fail per-path on a wrong guess and report "not found" for data that exists. Fetch the document or the schema first, then address paths.

## Picking a tool for a task

1. **"What is in my cluster?"** → `get_buckets_in_cluster`, then `get_scopes_and_collections_in_bucket`, then `get_schema_for_collection`.
2. **"Is it healthy?"** → `get_cluster_diagnostics_report` first (free, no network I/O, cached SDK state). Only reach for `get_cluster_health_and_services` when you need a live right-now answer — it actively pings every service, so narrow it with `service_types`.
3. **"Is my config right?"** → `get_server_configuration_status` reports read-only mode, disabled tools, confirmation-required tools, OAuth, and logging **without connecting to the cluster**. `test_cluster_connection` is the one that actually connects.
4. **One document by ID** → `get_document_by_id`. A few known fields of a large document → `lookup_subdocument`.
5. **Across documents** → `run_sql_plus_plus_query`. Relevance-scored, fuzzy, or linguistic matching → `run_fts_query`.
6. **"Why is this slow?"** → `explain_sql_plus_plus_query`, then `get_index_advisor_recommendations`. See `references/diagnostics.md`.
7. **"What is slow overall?"** → the `get_queries_*` family. See `references/diagnostics.md`.

If none of these fit, check `references/tool-index.md` before concluding the server cannot do it — and if it truly cannot, route to the Web Console, `couchbase-cli`, the Management REST API, or the Capella Management API v4.

## Worked examples

**"Show me my buckets"** — `get_buckets_in_cluster`. It returns a list of names. Do not query `system:keyspaces`.

**"What is in the `airline` collection?"** — `get_schema_for_collection(bucket_name, scope_name, "airline")`. It runs `INFER` server-side and returns the inferred schema, which is far more useful than a sample of raw documents.

**"Find the 10 most recent active users"** — `run_sql_plus_plus_query` scoped to the bucket and scope, bare collection name, `named_parameters` for any user-supplied filter value.

**"Why is this query slow?"** — `explain_sql_plus_plus_query` returns the plan plus a `plan_evaluation` block of findings. If it shows a primary-index scan or an uncovered fetch, follow with `get_index_advisor_recommendations` for candidate DDL. Treat advisor output as candidates, not commands — read `references/diagnostics.md` before recommending any index.

**"Create that index"** — a write. Confirm `CB_MCP_READ_ONLY_MODE=false`, state what the index will cost (build time, disk, write amplification), get explicit approval, then `create_index` (deferred by default) → `build_index` → `list_indexes` to confirm it reaches `online`.

**"Delete document X"** — a write and irreversible. Read `references/safety.md`. Show the document first, name it back to the user, get unambiguous confirmation, then `delete_document_by_id`. If the tool is absent, the server is in read-only mode: say so and point at the Web Console rather than proposing a config change.

**"Create a bucket" / "rebalance the cluster" / "add a Capella allowlist entry"** — not this server. One line: "the Couchbase MCP server is data-plane only; do this in the Couchbase Web Console, with `couchbase-cli`, or via the Management REST API (Capella: the Capella Management API v4)." Then stop.

## Related skills

- `couchbase-admin-mcp` — cluster administration (buckets, users/RBAC, rebalance, failover, XDCR, backup) through a separate admin MCP server. Everything this skill routes away from
- `couchbase-sqlpp-tuning` — SQL++ query and index tuning as a discipline, independent of MCP
- `couchbase-fts` — designing and operating Search Service indexes, beyond the three read-only FTS tools here
- `couchbase-performance-tuning` — cluster and workload performance work that goes past query-level diagnostics
- `couchbase-security-hardening` — cluster-wide security posture; this skill covers only the MCP server's own security surface
- `couchbase-capella` — Capella platform and control-plane work, which this server does not reach
- `cb-analytics-capella` — Capella Cloud Management API work through the separate cb-analytics-mcp server
- `cb-analytics-cluster` — node membership, rebalance and auto-failover through the separate cb-analytics-mcp server
- `couchbase-ai-applications` — RAG and retrieval design behind the vector indexes you create and query here
- `couchbase-migration-execution` — moving data into the buckets and collections created here, and validating parity afterwards
- `couchbase-sizing` — capacity math for the cluster these tools operate
- `couchbase-upgrade` — upgrade planning, compatibility and the 8.0 breaking changes behind the tool sequence
