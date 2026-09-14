# Tool families

What each family administers, which of its operations are read, write or destructive, and the
operations with the largest blast radius.

> **This file is deliberately not an exhaustive tool list.** The server carries roughly 268 tools and the
> inventory moves with every release. **Route exhaustive lookup to the server itself:** `cb_mcp_list_tools`
> enumerates every loaded tool with its read-only / destructive annotations, and `cb_mcp_get_tool_info`
> returns one tool's input schema and annotations. Those two are authoritative for the build you are
> connected to, ahead of anything written down anywhere, including here.

## Contents

- [How risk tiers work](#how-risk-tiers-work) · [Server status](#server-status) · [Buckets](#buckets) · [Scopes and collections](#scopes-and-collections) · [Cluster](#cluster)
- [Security](#security) · [Encryption](#encryption) · [Indexes](#indexes) · [Search](#search) · [Eventing](#eventing) · [XDCR](#xdcr) · [Backup](#backup)
- [Statistics](#statistics) · [Diagnostics](#diagnostics) · [8.x-only features](#8x-only-features) · [Capella](#capella) · [Cross-cutting: outbound egress](#cross-cutting-outbound-egress)

## How risk tiers work

Every tool is annotated `readOnlyHint` / `destructiveHint`. Three things read those annotations: the
read-only filter (which tools load), the OAuth scope gate, and the confirmation gate.

- **read** — loads in every mode, never gated, still executes under a forced dry run.
- **write** — mutates, but the change is ordinarily recoverable or bounded.
- **destructive** — data loss, topology change, or a configuration change that can lock you out or wedge a service.

An unannotated tool is treated as write-side: unknown intent gets the stronger gate. By default
*every* write tool requires `confirm: true`; the destructive tier is what should populate
`CB_ADMIN_ALWAYS_CONFIRM` on a production server.

## Server status

Administers nothing; reports this server's own posture. All read:
`cb_mcp_status` (safety mode, transport, auth method, tool counts, dry-run state — no
live cluster needed), `cb_mcp_list_tools`, `cb_mcp_get_tool_info`.

Call `cb_mcp_status` before proposing any change. It is the only honest answer to "can this server
write?"

## Buckets

Bucket lifecycle, memory quota, replicas, compression, storage backend, compaction, sample datasets.

- **read** — `admin_bucket_list`, `admin_bucket_get`, `admin_sample_buckets_list`
- **write** — `admin_bucket_create`, `admin_bucket_compact`, `admin_bucket_cancel_compaction`, `admin_sample_buckets_install`
- **destructive** — `admin_bucket_update`, `admin_bucket_delete`, `admin_bucket_flush`

`admin_bucket_create` takes `name`, `bucketType` (`couchbase` / `ephemeral`; memcached buckets are
deprecated since 6.5.1 and an existing one blocks the upgrade to 8.0), `ramQuota` in MB,
`replicaNumber`, `flushEnabled`, `compressionMode`, `storageBackend` (`couchstore` / `magma`). In Couchbase 8.x, magma defaults to 128
vBuckets with a 100 MiB minimum memory quota.

**Blast radius.** `admin_bucket_delete` removes the bucket and all its data,
irreversibly — nothing here restores it. `admin_bucket_flush` empties it in place (requires
`flushEnabled=1`); the bucket survives, so the symptom reads as data loss rather than a missing
bucket. `admin_bucket_update` is destructive because changing
`ramQuota` or `replicaNumber` on a live bucket reshapes memory and triggers data
movement — lowering a quota below the working set evicts.

## Scopes and collections

The Bucket → Scope → Collection hierarchy.

- **read** — `admin_scope_list`
- **write** — `admin_scope_create`, `admin_collection_create`
- **destructive** — `admin_scope_delete`, `admin_collection_delete`

**Blast radius.** `admin_scope_delete` removes the scope *and every collection in it*,
irreversibly; one scope name is all that separates "drop a test namespace" from "drop the
application's data". `admin_collection_delete` is irreversible for that collection's documents and
invalidates GSI indexes and Eventing functions bound to it.

## Cluster

Nodes, rebalance, failover and recovery, auto-failover, server groups (rack-zone awareness),
auto-compaction, email alerts, cluster-wide log collection, service memory quotas.

- **read** — `admin_cluster_info`, `admin_cluster_details`, `admin_cluster_tasks`, `admin_node_list`, `admin_node_services_list`, `admin_rebalance_progress`, `admin_autofailover_get`, `admin_server_groups_get`, `admin_autocompaction_get`, `admin_alerts_get`
- **write** — `admin_cluster_name_set`, `admin_recovery_type_set`, `admin_autofailover_reset`, `admin_server_group_create`, `admin_server_group_rename`, `admin_logs_collect_cancel`, `admin_autocompaction_set`, `admin_alerts_set`, `admin_alerts_test_email`
- **destructive** — `admin_cluster_memory_set`, `admin_node_add`, `admin_node_remove`, `admin_rebalance_start`, `admin_rebalance_stop`, `admin_failover_hard`, `admin_failover_graceful`, `admin_autofailover_set`, `admin_server_group_delete`, `admin_logs_collect_start`

This family has the widest blast radius in the server, and its operations serialize: a rebalance, a
failover and a recovery cannot be in flight at once. `admin_cluster_tasks` is how you find out what
is already running.

**Blast radius.**

- `admin_failover_hard` — forcibly removes a node and **may cause data loss for
  unreplicated documents**. No undo; the node returns only through recovery plus
  rebalance.
- `admin_failover_graceful` — no data loss on a properly replicated bucket, but capacity
  drops immediately and the cluster runs degraded until rebalance.
- `admin_rebalance_start` — moves data across every bucket at once and stresses the
  cluster for the duration. Takes `ejectedNodes` / `knownNodes` as OTP strings; a wrong
  node list ejects the wrong node.
- `admin_rebalance_stop` — leaves a partially moved state that only another rebalance
  resolves.
- `admin_node_remove` — the data-loss risk materializes at the following rebalance.
- `admin_cluster_memory_set` — `dataMemoryQuota`, `indexMemoryQuota`, `ftsMemoryQuota`,
  `eventingMemoryQuota` and the analytics quota. Misconfiguration can crash services.
- `admin_autofailover_set` — arms an **automatic** topology change. Wrong thresholds mean
  the cluster fails a node over with no human in the loop. `failoverOnDataDiskIssues` and
  `canAbortRebalance` are forwarded here.
- `admin_logs_collect_start` — every node gathers a diagnostic bundle and uploads it to a
  caller-named host. Bundles contain query text, document keys and configuration. One
  call is "send me all your logs"; the egress allowlist exists largely for this.
- `admin_alerts_set` — `/settings/alerts` is a full replace upstream; this tool reads
  current settings and merges, so a partial call changes only what you name. Do not
  assume that property of the raw REST endpoint.

## Security

Local and external users, groups, RBAC roles, audit configuration, password policy, global TLS and
security settings.

- **read** — `admin_user_list`, `admin_user_get`, `admin_group_list`, `admin_group_get`, `admin_role_list`, `admin_whoami`, `admin_audit_get`, `admin_password_policy_get`, `admin_security_settings_get`
- **write** — `admin_group_create`
- **destructive** — `admin_user_create`, `admin_user_delete`, `admin_user_change_password`, `admin_group_delete`, `admin_audit_set`, `admin_password_policy_set`, `admin_security_settings_set`

`admin_user_create` is create-or-update and takes `roles` as a comma-separated string,
e.g. `admin` or `bucket_admin[travel-sample]`. `admin_whoami` returns the identity this server
actually authenticates as — the first call when the *cluster*, rather than a gate, refuses
something.

**Blast radius.** `admin_security_settings_set` (`tlsMinVersion`, `honorCipherOrder`,
`cipherSuites`) can **lock every client, including this server, out of the cluster**, and
the fix then happens out of band. `admin_user_delete` breaks everything authenticating as that user
immediately, and the role grants are not recoverable here.
`admin_user_create` is destructive precisely because it is create-*or-update*: run
against an existing user it replaces roles and password. `admin_audit_set` can switch auditing off —
both a change and the loss of the record of it.
`admin_password_policy_set` with a policy no existing credential satisfies blocks
rotation.

## Encryption

Data-at-Rest Encryption (DARE) and the KMIP server connection that sources the master key.

- **read** — `admin_encryption_get`, `admin_kmip_get`
- **destructive** — `admin_encryption_set`, `admin_kmip_set`

Couchbase 7.x has partial DARE support; 8.x has first-class configuration. Field names vary by
version — read the current configuration with `admin_encryption_get` before writing rather than
assuming a shape.

**Blast radius.** `admin_kmip_set` repoints where the cluster fetches its master key;
aimed wrong, **the cluster cannot decrypt its own data after a restart**, and the failure surfaces
only at that restart. `admin_encryption_set` (`keySource` =
`master_password` | `kmip`, `rotateInterval`, `algorithm`) can render data unreadable.

On Capella these are not withheld so much as reassigned: DARE and KMIP become CMEK, managed by
Couchbase as the operator.

## Indexes

Global Secondary Indexes (GSI) and Index Service settings.

- **read** — `admin_index_list`, `admin_index_settings_get`
- **write** — `admin_index_create`, `admin_index_build`, `admin_index_settings_set`
- **destructive** — `admin_index_drop`

`admin_index_create` takes a full SQL++ statement and accepts only `CREATE INDEX`,
`CREATE PRIMARY INDEX`, `CREATE [HYPERSCALE|COMPOSITE] VECTOR INDEX` or `BUILD INDEX`;
`admin_index_drop` accepts only `DROP INDEX` / `DROP PRIMARY INDEX` / `DROP VECTOR
INDEX`.

**Blast radius.** `admin_index_drop` sends dependent queries to a primary scan or
outright failure, and rebuilding a large index takes as long as it takes.
`admin_index_settings_set` (`indexerThreads`, snapshot intervals, `maxRollbackPoints`)
degrades indexing cluster-wide if set wrong. `admin_index_create` on a large collection consumes
index-service memory and CPU while building; deferred creation plus a deliberate `admin_index_build`
is the controlled path.

## Search

Search Service index lifecycle, statistics and ingest control.

- **read** — `admin_fts_index_list`, `admin_fts_index_get`, `admin_fts_index_stats`, `admin_fts_index_doc_count`, `admin_fts_settings_get`
- **write** — `admin_fts_index_ingest_pause`, `admin_fts_index_ingest_resume`
- **destructive** — `admin_fts_index_create`, `admin_fts_index_delete`

`admin_fts_index_create` is create-*or-update*, which is why it is destructive: applied
to an existing name it replaces the definition and the index rebuilds from scratch. Minimum keys are
`name`, `type` (`fulltext-index`) and `sourceName` (the bucket).

**Blast radius.** `admin_fts_index_delete` fails search queries immediately and a rebuild
is a full re-index. `admin_fts_index_ingest_pause` quietly stops the index converging — queries keep
succeeding against stale data, which is worse than failing.

Search index administration is the one genuine gap on Capella: there is no Management API v4
equivalent.

## Eventing

Eventing function lifecycle and runtime state.

- **read** — `admin_eventing_list`, `admin_eventing_get`, `admin_eventing_stats`, `admin_eventing_status`
- **write** — `admin_eventing_pause`, `admin_eventing_resume`
- **destructive** — `admin_eventing_create_or_update`, `admin_eventing_delete`, `admin_eventing_deploy`, `admin_eventing_undeploy`

The `definition` for create-or-update is the complete function JSON: `appname`,
`appcode` (the JavaScript), `depcfg` (source bucket/scope/collection plus bindings) and
`settings`.

Pause and undeploy are **not** the same thing. Pause preserves the checkpoint and resume continues
from it. Undeploy discards the checkpoint: the source survives and can be redeployed, but mutations
that occurred while undeployed are not replayed.

**Blast radius.** `admin_eventing_deploy` starts processing mutations immediately,
including whatever side effects the code has on other collections or external systems (returns a
task id; monitor with `admin_eventing_status`). `admin_eventing_undeploy` discards the checkpoint.
`admin_eventing_delete` removes the source code irreversibly and requires the function be undeployed
first. `admin_eventing_create_or_update` replaces an existing function wholesale.

## XDCR

Remote cluster references, replications, and global or per-replication settings.

- **read** — `admin_xdcr_references_list`, `admin_xdcr_replications_list`, `admin_xdcr_settings_get`
- **write** — `admin_xdcr_reference_create`, `admin_xdcr_replication_pause`, `admin_xdcr_replication_resume`, `admin_xdcr_settings_set`
- **destructive** — `admin_xdcr_reference_delete`, `admin_xdcr_replication_create`, `admin_xdcr_replication_delete`

**Blast radius.** `admin_xdcr_replication_create` is destructive because it starts
streaming an entire bucket continuously to another cluster *and writes into the target* — bulk
outbound data movement to a caller-named destination, which is why it is subject to the egress
allowlist. `admin_xdcr_replication_delete` makes the target silently stop converging; the gap is
usually found much later, during a failover test or an audit.
`admin_xdcr_reference_delete` fails while active replications exist — that is the desired
behaviour, so do not force ordering around it. `admin_xdcr_settings_set` applied globally hits every
replication at once.

## Backup

The Backup Service (plans, repositories, runs, restore), plus a local catalogue for tagging backups
on either plane.

- **read** — `admin_backup_repository_list`, `admin_backup_plans_list`, `admin_backup_repository_get`, `admin_backup_list`
- **write** — `admin_backup_repository_create`, `admin_backup_run`
- **destructive** — `admin_backup_restore_run`

The Backup Service must be running on at least one node. A repository must name a
**plan** — `admin_backup_plans_list` shows what the service knows, including built-ins
such as `_daily_backups` and `_hourly_backups` — and an archive path the **backup service** can
write, which is a path inside the service's own filesystem, not the caller's.

The catalogue tools (`cb_backup_catalog_record`, `_list`, `_get`, `_update`, `_delete`,
`_sync`) record user-defined tags pointing at backups that already exist on either plane,
answering questions neither plane can ("latest where content-publisher-version = 1.6"). They are
local-filesystem only and do not copy data. `cb_backup_catalog_delete` deletes a catalogue
**entry**, never a backup. `cb_backup_catalog_sync` marks entries present, missing or unchecked and
never deletes them, because "expired on schedule" and "someone deleted the wrong thing" look
identical from here.

**Blast radius.** `admin_backup_restore_run` **overwrites data in the target cluster** —
the only tool in this family that destroys anything, and the only one where pointing at the wrong
cluster is unrecoverable. `admin_backup_run` is asynchronous (task id, monitored through
`admin_cluster_tasks`); its cost is I/O and archive space.

## Statistics

Mostly reads metrics; two exceptions write.

- **read** — `admin_stats_bucket`, `admin_stats_single`, `admin_stats_multi`, `admin_system_events`, `admin_node_self_info`, `admin_internal_settings_get`, `admin_query_settings_get`, `admin_prometheus_targets`
- **write** — `admin_query_settings_set`
- **destructive** — `admin_internal_settings_set`

`admin_stats_single` takes a Prometheus-style metric name (`kv_num_items`,
`index_ram_percent`, `n1ql_requests`); `admin_stats_multi` posts several in one call.
`admin_prometheus_targets` is one of the few `admin_*` tools that also works against
Capella, using a database credential with read on all buckets.

**Blast radius.** `admin_internal_settings_set` is advanced use only — its own
description says misconfiguration can **wedge a cluster**. `admin_query_settings_set`
(`queryTmpSpaceDir`, `queryTmpSpaceSize`, `queryTimeout`, `queryMaxParallelism` and similar)
degrades every query on the cluster at once if set wrong.

## Diagnostics

All read-only, and all still execute under a forced dry run:
`cb_get_schema_for_collection`, `cb_index_advisor`, `cb_explain_query`,
`cb_perf_longest_running`, `cb_perf_most_frequent`, `cb_perf_largest_responses`,
`cb_perf_large_result_count`, `cb_perf_using_primary_index`,
`cb_perf_not_using_covering_index`, `cb_perf_not_selective`.

Two caveats the tools state themselves: `cb_perf_using_primary_index` is heuristic (it reads
`phaseOperators` from `system:completed_requests` where available, with a statement-pattern fallback), so
confirm with `cb_explain_query`; and `cb_perf_not_using_covering_index` re-runs EXPLAIN on the most
recent N queries and is slow for large N. These work against Capella too, because they go through the query service with
a database credential rather than the management API.

## 8.x-only features

These have **no pre-8.0 equivalent**. Confirm the cluster version before proposing any of them;
against a 7.x cluster they will not work.

| Tool | Tier | Requires |
|---|---|---|
| `admin_vector_index_create_hyperscale` | write | Couchbase 8.0+ |
| `admin_vector_index_create_composite` | write | Couchbase 8.0+ |
| `admin_user_lock` | destructive | Couchbase 8.0+ |
| `admin_user_unlock` | write | Couchbase 8.0+ |
| `admin_user_create_temporary` | destructive | Couchbase 8.0+ |
| `admin_xdcr_conflict_log_query` | read | Couchbase 8.0+ |

Hyperscale vector index: billion-scale ANN search where filtering is rare. Composite vector index: a
vector field plus scalar prefix keys for filtered ANN search (tenant id + status + embedding) — use
this one when queries include a `WHERE` on the scalar fields.
`admin_user_lock` leaves the user queryable by admins but **unable to authenticate**,
which is an immediate outage for anything holding that credential.
`admin_user_create_temporary` is `admin_user_create` with `temporaryPassword=true` and is
destructive for the same create-or-update reason. `admin_xdcr_conflict_log_query` only reads the
conflict log collection; the log must already be configured on the replication via
`admin_xdcr_replication_create` with `conflictLogging=true` and a
`conflictLoggingMapping`.

## Capella

The Capella control plane through Management API v4, authenticated with an organization API key —
**not** cluster credentials. A Capella database credential carries bucket-scoped data roles and
never Full Admin, so the `admin_*` tools cannot work against Capella and are unloaded when a Capella
connection string is detected.

| Group | Read | Write | Destructive |
|---|---|---|---|
| Organizations, projects | `capella_organizations_list`, `capella_projects_list`, `capella_project_get` | `capella_project_create`, `capella_project_update` | `capella_project_delete` |
| Clusters | `capella_clusters_list`, `capella_cluster_get`, `capella_cluster_stats_get` | `capella_cluster_create`, `capella_cluster_update`, `capella_cluster_turn_on`, `capella_cluster_turn_off`, `capella_cluster_onoff_schedule_set` | `capella_cluster_delete`, `capella_cluster_onoff_schedule_delete` |
| Buckets, scopes, collections | `capella_buckets_list`, `capella_scopes_list`, `capella_collections_list` | `capella_bucket_create`, `capella_bucket_update`, `capella_scope_create`, `capella_collection_create`, `capella_sample_bucket_load` | `capella_bucket_delete`, `capella_bucket_flush`, `capella_scope_delete`, `capella_collection_delete` |
| Database credentials | `capella_database_credentials_list`, `capella_database_credential_get` | `capella_database_credential_create`, `capella_database_credential_update` | `capella_database_credential_delete` |
| Allowed CIDRs | `capella_allowed_cidrs_list` | `capella_allowed_cidr_create` | `capella_allowed_cidr_delete` |
| App Services | `capella_app_services_list`, `capella_app_service_get`, `capella_app_service_certificate_get`, `capella_app_service_admin_users_list` | `capella_app_service_create`, `capella_app_service_update`, `capella_app_service_turn_on`, `capella_app_service_turn_off`, `capella_app_service_allowed_cidr_create`, `capella_app_service_admin_user_create` | `capella_app_service_delete`, `capella_app_service_admin_user_delete` |
| App Endpoints | `capella_app_endpoints_list`, `capella_app_endpoint_get`, `capella_app_endpoint_resync_status` | `capella_app_endpoint_create`, `capella_app_endpoint_update`, `capella_app_endpoint_online`, `capella_app_endpoint_offline`, `capella_app_endpoint_access_control_function_set`, `capella_app_endpoint_cors_set`, `capella_app_endpoint_import_filter_set`, `capella_app_endpoint_resync_start` | `capella_app_endpoint_delete`, `capella_app_endpoint_import_filter_delete` |
| Events, certificates | `capella_events_list`, `capella_event_get`, `capella_project_events_list`, `capella_cluster_certificate_get` | — | — |
| Audit log, alerts | `capella_cluster_audit_log_config_get`, `capella_cluster_audit_log_events_list`, `capella_alert_integrations_list` | `capella_cluster_audit_log_config_set`, `capella_cluster_audit_log_export_create`, `capella_alert_integration_create` | `capella_alert_integration_delete` |
| Backups | `capella_backups_list`, `capella_backup_get`, `capella_cloud_snapshot_backups_list` | `capella_backup_create` | `capella_backup_restore`, `capella_backup_cycle_delete` |
| Eventing, query indexes | `capella_eventing_functions_list`, `capella_query_index_definitions_list`, `capella_query_index_build_status` | `capella_eventing_function_create`, `capella_eventing_function_state_set`, `capella_query_index_manage` | `capella_eventing_function_delete` |
| Replications | `capella_replications_list`, `capella_replication_get` | `capella_replication_create` | `capella_replication_delete` |

**Blast radius.**

- `capella_cluster_delete` — deletes the cluster and everything in it, irreversibly.
  Refused unless the cluster is in an allowlisted project, its name carries the configured
  prefix, and Capella deletion protection is off. Delete any attached App Service first.
- `capella_backup_restore` — overwrites the target.
- `capella_database_credential_update` — `access` **replaces** existing grants rather than
  adding to them, so omitting a privilege revokes it; read the current grants with
  `capella_database_credential_get` first. Rotation today means delete and recreate, so
  every client holding the old password fails in the window between.
- `capella_allowed_cidr_create` — prefer a `/32` for a single client and set `expiresAt`
  so a temporary rule cannot outlive the test run. `0.0.0.0/0` exposes the cluster to the
  whole internet.
- `capella_database_credential_create` — if `password` is omitted, Capella generates one
  and returns it **in that response only**. It cannot be retrieved later.

### Ephemeral environments

Standing up a throwaway cluster is not one call: create cluster, wait, allowlist the client, create
a bucket and credential, create an App Service, wait again, create an App Endpoint, bring it online
— and teardown is that list backwards with ordering constraints. These tools do it as a reconciler.

| Tool | Tier | Purpose |
|---|---|---|
| `capella_env_ensure` | write | Converge an environment. Non-blocking: returns `{phase, done, retry_after_s}`; call again until `phase == "ready"`. Phases: `creating_cluster → waiting_for_cluster → configuring → creating_app_service → waiting_for_app_service → configuring_app_endpoint → ready`. Repeat calls reuse existing resources, never duplicate. |
| `capella_env_status` | read | Cluster and App Service state, buckets, allowlist, TTL remaining. Poll with this, not with `ensure`. |
| `capella_env_list` | read | Every managed environment with age and expiry. Clusters with no `mcp-env` marker are reported separately as unmanaged and are explicitly not reapable. |
| `capella_env_connection_info` | read | Connection string, App Services endpoint and websocket URL, keyspace names, credential username, current allowlist. |
| `capella_env_park` / `capella_env_resume` | write | Turn off / on without destroying — keeps the data and avoids paying the provisioning wait again. |
| `capella_env_teardown` | destructive | App Service first, then cluster. Irreversible. |
| `capella_env_reap` | destructive | Tear down expired environments. **Its own `dry_run` defaults to true.** |
| `capella_guardrails_status` | read | The server's effective Capella blast radius, answered by the code that enforces it. |

There is **no local state file**: everything is derived from Capella through a naming convention plus an
`mcp-env:{...}` marker in the cluster description, so a CI job that dies mid-provision leaves no orphaned
bookkeeping. Preserve that marker if you edit a description by hand, or the environment stops being
recognized as managed. The credential password appears only in the call that created it — capture it then.

### Fixtures

| Tool | Tier | Purpose |
|---|---|---|
| `capella_fixture_export` | read (of the cluster) | Export structure, GSI and Search index definitions, Eventing functions, and document bodies with expiry, to a manifest plus JSON Lines payload. |
| `capella_fixture_list` | read | List fixtures under a root and filter on their tags. Local filesystem only. |
| `capella_fixture_verify` | read | Validate a fixture, or verify a cluster imported from one — including that every GSI index named in the manifest is **ONLINE**, not merely defined. |
| `capella_fixture_import` | destructive | Create buckets, scopes and collections, load documents, apply Search index definitions, create Eventing functions, then create **and build** the GSI indexes, polling until every index is online. |

Two limits the tools state themselves: export is **not a backup** — it iterates rather than
snapshotting, so it is not point-in-time consistent (run it against a quiesced cluster) and CAS is
not preserved by any documented Capella API. And although export is annotated read-only, that is
true of the *cluster*, not the disk: it writes files, confined by `CB_ADMIN_FIXTURE_ROOT`.

## Cross-cutting: outbound egress

Several tools take a hostname from the caller and make **Couchbase itself** dial out:
`admin_logs_collect_start` (`uploadHost`), `admin_xdcr_reference_create` (`hostname`),
`admin_node_add` (`hostname`), `admin_kmip_set` (`kmipHost`), `admin_alerts_set`
(`emailHost`) and `admin_alerts_test_email`.

Every such destination is checked against `CB_ADMIN_EGRESS_ALLOWED_HOSTS` before the call is issued,
and loopback, link-local and cloud-metadata addresses are always refused. A rejection there is
policy, not a broken tool: the fix is an operator adding the destination to the allowlist, never
working around it.
