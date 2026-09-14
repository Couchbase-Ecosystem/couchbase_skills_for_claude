# Tool index — all 37 tools

Every tool the official Couchbase MCP server exposes, with its arguments. **25 read-only** tools are always loaded; **12 write** tools load only when `CB_MCP_READ_ONLY_MODE=false`.

If an operation is not on this page, this server does not have it. See [Not in this server](#not-in-this-server).

## Contents

- [Cluster and server](#cluster-and-server)
- [Schema discovery](#schema-discovery)
- [Key-value](#key-value)
- [Query and index](#query-and-index)
- [Search (FTS)](#search-fts)
- [Query performance](#query-performance)
- [Scope and collection management (write)](#scope-and-collection-management-write)
- [Write tools at a glance](#write-tools-at-a-glance)
- [Version gates](#version-gates)
- [Not in this server](#not-in-this-server)

Common argument names throughout: `bucket_name`, `scope_name`, `collection_name`, `document_id`, `index_name`, `query`, `limit`.

## Cluster and server

All read-only.

| Tool | Arguments | Returns |
|---|---|---|
| `get_server_configuration_status` | — | Server status and configuration **without connecting to the cluster**: read-only mode, disabled tools, confirmation-required tools, OAuth settings, resolved logging config |
| `test_cluster_connection` | `bucket_name?` | Verifies the configured credentials by actually connecting. Optionally checks access to one bucket |
| `get_cluster_health_and_services` | `bucket_name?`, `service_types?` | **Actively pings** services; per-service reachability, latency, responding endpoint, errors. `service_types`: `key_value`, `query`, `search`, `analytics`, `view`, `management`, `eventing` |
| `get_cluster_diagnostics_report` | — | SDK's cached connection state — **no network I/O**. Per-endpoint service, addresses, connection state, `last_activity`; overall online/degraded/offline |

## Schema discovery

All read-only.

| Tool | Arguments | Returns |
|---|---|---|
| `get_buckets_in_cluster` | — | List of bucket names |
| `get_scopes_in_bucket` | `bucket_name` | List of scope names |
| `get_collections_in_scope` | `bucket_name`, `scope_name` | List of collection names. **Requires the Query Service** |
| `get_scopes_and_collections_in_bucket` | `bucket_name` | Scope → collections map for the whole bucket. Usually the one call you want |
| `get_schema_for_collection` | `bucket_name`, `scope_name`, `collection_name` | Inferred structure, via a server-side `INFER` query |

## Key-value

| Tool | Arguments | Mode |
|---|---|---|
| `get_document_by_id` | `bucket_name`, `scope_name`, `collection_name`, `document_id` | read — raises if not found |
| `lookup_subdocument` | keyspace, `document_id`, and at least one of `get_paths`, `exists_paths`, `count_paths` | read |
| `upsert_document_by_id` | keyspace, `document_id`, `document_content` | **write** — insert or replace |
| `insert_document_by_id` | keyspace, `document_id`, `document_content` | **write** — fails if the ID exists |
| `replace_document_by_id` | keyspace, `document_id`, `document_content` | **write** — fails if the ID does not exist |
| `delete_document_by_id` | keyspace, `document_id` | **write** — irreversible |
| `mutate_subdocument` | keyspace, `document_id`, plus any of `upsert_specs`, `insert_specs`, `replace_specs`, `remove_paths`, `array_append_specs`, `array_prepend_specs`, `array_insert_specs`, `array_add_unique_specs`, `counter_specs`, `create_parents` | **write** — document must exist; all-or-nothing |

Sub-document paths use dot/bracket syntax (`address.city`, `tags[0]`, `tags[-1]`). Keep the combined path count per lookup at 16 or fewer.

## Query and index

| Tool | Arguments | Mode |
|---|---|---|
| `run_sql_plus_plus_query` | `bucket_name`, `scope_name`, `query`, `named_parameters?` | read or **write** by statement — guarded under read-only mode |
| `explain_sql_plus_plus_query` | `bucket_name`, `scope_name`, `query` | read — returns `plan` plus `plan_evaluation` |
| `list_indexes` | `bucket_name?`, `scope_name?`, `collection_name?`, `index_name?`, `return_raw_index_stats?` | read — filters are hierarchical |
| `get_index_advisor_recommendations` | `bucket_name`, `scope_name`, `query` | read — SELECT, UPDATE, DELETE, MERGE |
| `create_index` | `bucket_name`, `scope_name`, `collection_name`, `index_name`, `keys`, `deferred?` (default true), `condition?`, `num_replicas?`, `ignore_if_exists?` | **write** — scalar GSI only, not vector |
| `build_index` | `bucket_name`, `scope_name`, `collection_name` | **write** — builds all deferred indexes on the collection |
| `drop_index` | `bucket_name`, `scope_name`, `collection_name`, `index_name` | **write** — scalar or vector |

The query runs inside the given scope, so use bare collection names. Bind user input through `named_parameters` against `$name` placeholders.

## Search (FTS)

All read-only. **Requires Couchbase Server 7.6+ and the Search Service.** Vector search is not supported by these tools.

| Tool | Arguments | Notes |
|---|---|---|
| `list_fts_indexes` | `bucket_name?`, `scope_name?` | No filters → cluster-level (legacy) indexes; `bucket_name` → scope-level indexes across the bucket; both → one scope. `scope_name` alone is invalid |
| `get_fts_index_definition` | `index_name`, `bucket_name?`, `scope_name?` | Full definition: mappings, analyzers, plan params. Pass both bucket and scope for a scoped index, neither for cluster-level |
| `run_fts_query` | `index_name`, `query`, `bucket_name?`, `scope_name?`, `explain?`, `limit?`, `skip?`, `fields?`, `sort?`, `facets?`, `highlight_fields?`, `disable_scoring?`, `raw?` | `query` is the raw FTS query JSON body. `explain=true` still executes the query (limit defaults to 1) |

## Query performance

All read-only. All take `limit` (default 10). Sourced from the Query Service's record of completed requests.

| Tool | Ranks by |
|---|---|
| `get_longest_running_queries` | Average service time |
| `get_most_frequent_queries` | Execution count |
| `get_queries_with_largest_response_sizes` | Result payload size |
| `get_queries_with_large_result_count` | Rows returned |
| `get_queries_using_primary_index` | Use of a primary index |
| `get_queries_not_using_covering_index` | Fetching documents the index did not cover |
| `get_queries_not_selective` | Scans returning far more than the final result |

## Scope and collection management (write)

All four are **write** tools. **Couchbase Server 7.6+ and Capella.**

| Tool | Arguments | Notes |
|---|---|---|
| `create_scope` | `bucket_name`, `scope_name` | |
| `create_collection` | `bucket_name`, `scope_name`, `collection_name` | Scope must exist |
| `delete_scope` | `bucket_name`, `scope_name` | Deletes the scope **and all its collections**. Permanent |
| `delete_collection` | `bucket_name`, `scope_name`, `collection_name` | Deletes the collection **and all its documents**. Permanent |

There is no bucket management here.

## Write tools at a glance

The complete set that disappears under `CB_MCP_READ_ONLY_MODE=true` (the default):

```
upsert_document_by_id     insert_document_by_id     replace_document_by_id
delete_document_by_id     mutate_subdocument
create_scope              create_collection
delete_scope              delete_collection
create_index              build_index               drop_index
```

Read `safety.md` before composing any of these.

## Version gates

| Feature | Requirement |
|---|---|
| Scope and collection management tools | Couchbase Server 7.6+ and Capella |
| Search (FTS) tools | Couchbase Server 7.6+ and the Search Service |
| `list_indexes` via `system:indexes` (Query Service, RBAC-scoped) | Couchbase Server 8.0+ |
| `list_indexes` via the Index Service REST API | 7.x fallback — admin-level, not RBAC-scoped |
| KV service coverage in cluster-level `get_cluster_health_and_services` | Version-dependent; pass `bucket_name` to guarantee it |
| Server runtime | Python 3.10+ |

## Not in this server

This is a data-plane server. If the task is on this list, say so in one line and route the user to the right surface rather than improvising.

| Not available | Where it lives |
|---|---|
| Bucket create/edit/delete/flush | Couchbase Web Console, `couchbase-cli`, Management REST API |
| Users, groups, roles, RBAC administration | Same |
| Rebalance, failover, recovery, node add/remove, server groups | Same |
| XDCR replication | Same |
| Eventing functions | Same |
| Backup and restore | Same, or Couchbase Backup Service |
| Encryption at rest, KMIP, key rotation | Same |
| Audit configuration, password policy, cluster security settings | Same |
| Alerts, logs, cluster statistics and monitoring | Couchbase Web Console statistics, or the cluster's metrics pipeline |
| Vector index creation, vector search | Not in these tools — Search Service surfaces outside this server |
| Analytics queries (Capella Analytics / Couchbase Enterprise Analytics) | Analytics Service interfaces, not this server |
| Multi-document transactions | Couchbase SDKs |
| Capella organizations, projects, clusters, database users, allowed CIDRs, app services | Capella UI or the Capella Management API v4 |

For the same surfaces driven over MCP, see the `couchbase-admin-mcp` skill.
