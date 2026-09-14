# Operational runbooks

End-to-end procedures using the Couchbase Admin MCP server. Each is written as **preconditions → dry run →
execute → verify → rollback position**, and each states plainly where the point of no return is. Where a
rollback does not exist, it says so rather than inventing one. These runbooks describe *how to drive this
server safely*; they do not replace the judgement call about whether to make the change.

## Contents

- [Before any runbook](#before-any-runbook) · [1. Add a node and rebalance](#1-add-a-node-and-rebalance) · [2. Remove a node safely](#2-remove-a-node-safely)
- [3. Recover after a failover](#3-recover-after-a-failover) · [4. Create and correctly size a bucket](#4-create-and-correctly-size-a-bucket) · [5. Rotate a user credential](#5-rotate-a-user-credential)
- [6. Stand up an XDCR replication](#6-stand-up-an-xdcr-replication) · [7. Deploy an Eventing function](#7-deploy-an-eventing-function) · [8. Run and verify a backup](#8-run-and-verify-a-backup)
- [9. Turn on encryption at rest](#9-turn-on-encryption-at-rest) · [10. Provision a Capella project, cluster, credential and CIDR](#10-provision-a-capella-project-cluster-credential-and-cidr)

## Before any runbook

Three checks, every time, before proposing a change:

1. `cb_mcp_status` — which profile, is it read-only, is `CB_ADMIN_DRY_RUN` on, what cluster version. Never
   infer posture from a failed call.
2. `cb_mcp_list_tools` — is the tool you intend to use actually loaded. If a write tool is missing, the
   server is read-only or the tool is disabled; that is a configuration answer, not a tool-missing
   answer.
3. `admin_cluster_tasks` — is something already running. Topology operations serialize; do not start a
   second one.

Then: dry run, show the operator what it reports, get explicit approval naming the cluster and the object,
and only then make the real call with `confirm: true`. One change at a time — do not batch unrelated
cluster changes into one turn because they were all requested at once.

## 1. Add a node and rebalance

**Preconditions**
- `admin_node_list` and `admin_node_services_list` — current topology and what each node runs. Note the
  OTP node strings; rebalance takes those, not hostnames.
- The new node is installed, reachable from the cluster, and running a compatible version. The cluster
  dials *out* to it, so the hostname must satisfy `CB_ADMIN_EGRESS_ALLOWED_HOSTS` or the call is refused
  by policy.
- Decide the service set for the new node before the call. Services are set at add time.
- If server groups are in use, decide which group (`admin_server_groups_get`).
- Cluster is healthy and no rebalance, failover or recovery is in flight.

**Dry run**
`admin_node_add` with `dry_run: true`, then `admin_rebalance_start` with `dry_run: true`
and the full `knownNodes` list. Read back the node list in the preview and confirm the new node's OTP
string is present and nothing is in `ejectedNodes`.

**Execute**
1. `admin_node_add` with `confirm: true`. The node joins as *pending* — it holds no data yet.
2. `admin_rebalance_start` with `confirm: true`, passing `knownNodes` including the new node and an empty
   `ejectedNodes`.

**Verify**
- `admin_rebalance_progress` until it completes; issue no other topology calls while it runs.
- `admin_node_list` — the new node is active and healthy. `admin_stats_bucket` on a representative bucket
  — items and resident ratio have redistributed.

**Rollback position**
- Before step 2: full. A pending node that has not been rebalanced in holds no data; remove it and
  nothing moved.
- After step 2 starts: **this is the point of no return.** Data has moved. There is no "undo rebalance" —
  the only way back is to eject the node and rebalance again, which is a second full data movement.
  `admin_rebalance_stop` aborts, but leaves a partially moved cluster that another rebalance must
  resolve.

## 2. Remove a node safely

**Preconditions**
- `admin_node_list` — identify the node's OTP string exactly. This is the call where naming the wrong
  node is unrecoverable.
- Check replica counts on every bucket (`admin_bucket_list` / `admin_bucket_get`). On a bucket with
  `replicaNumber: 0`, removing a node removes the only copy of its data.
- Confirm the remaining nodes can hold the data and serve the load; this server will not check that for
  you. Nothing else in flight (`admin_cluster_tasks`).

**Dry run**
`admin_node_remove` with `dry_run: true`, then `admin_rebalance_start` with
`dry_run: true` and the node in `ejectedNodes`. Confirm the previewed `ejectedNodes` list
contains exactly the node you meant and nothing else.

**Execute**
1. `admin_node_remove` with `confirm: true` — marks the node for ejection.
2. `admin_rebalance_start` with `confirm: true`, with that node in `ejectedNodes`.

**Verify**
- `admin_rebalance_progress` to completion; `admin_node_list` — the node is gone.
- `admin_stats_bucket` — item counts unchanged, resident ratio on the remaining nodes still acceptable.

**Rollback position**
- Between step 1 and step 2: full. The node is marked but still in the cluster; clear the marking by
  rebalancing with it back in `knownNodes`.
- Once the rebalance in step 2 starts: **point of no return.** Data is being moved off the node.
  Re-adding it afterwards is a fresh `admin_node_add` plus another rebalance, not a rollback.

## 3. Recover after a failover

**Preconditions**
- `admin_node_list` and `admin_cluster_details` — confirm the node is in a failed-over state and is now
  reachable and healthy again.
- Know which failover happened. After a **hard** failover, unreplicated documents that were on that node
  are already gone; recovery does not bring them back.
- Choose the recovery type deliberately:
  - **delta** — the node keeps its existing data and catches up. Faster, and only valid when the node's
    data files are intact and not too far behind.
  - **full** — the node's data is discarded and rebuilt from the cluster. Slower, always valid.
- If auto-failover fired, `admin_autofailover_get` for the current configuration and
  `admin_autofailover_reset` to clear the counter, so a later incident is also handled automatically.

**Dry run**
`admin_recovery_type_set` with `dry_run: true`, then `admin_rebalance_start` with
`dry_run: true`. Confirm the previewed node and recovery type.

**Execute**
1. `admin_recovery_type_set` — set `delta` or `full` on the failed-over node.
2. `admin_rebalance_start` with `confirm: true`. Recovery only takes effect at rebalance.

**Verify**
- `admin_rebalance_progress` to completion; `admin_node_list` — the node is active, not failed-over.
- `admin_stats_bucket` — replica counts are healthy again on the affected buckets.

**Rollback position**
- Between step 1 and step 2: full. The recovery type is a marking; change it or clear it.
- **Choosing `full` is the point of no return for that node's local data** — it is discarded at
  rebalance. If you are unsure whether delta is valid, full is the safe choice for correctness and the
  expensive one for time; there is no way back from full to delta once the rebalance has started.
- **Data lost in a preceding hard failover has no rollback at all.** No recovery type restores it. If
  that data matters, restore from backup instead of recovering the node — see runbook 8.

## 4. Create and correctly size a bucket

**Preconditions**
- `admin_cluster_info` — the cluster's data memory quota and how much is already committed to existing
  buckets. A bucket cannot be created beyond the quota.
- Decide first: `bucketType` (`couchbase` / `ephemeral`; memcached buckets were removed in 8.0 and block the upgrade),
  `ramQuota` in MB, `replicaNumber`, `flushEnabled`, `compressionMode`, `storageBackend` (`couchstore` / `magma`).
- Version-specific: **in Couchbase 8.x, magma defaults to 128 vBuckets with a 100 MiB minimum memory
  quota.** Sizing below that is refused.
- Leave `flushEnabled` at 0 unless the bucket genuinely needs flush. Enabling it is what makes
  `admin_bucket_flush` possible later.

**Dry run**
`admin_bucket_create` with `dry_run: true`. Read the previewed arguments back against the
intended sizing. Remember: a dry run validates the request, **not** the cluster's acceptance of it — it
will preview cleanly even if the quota is unavailable.

**Execute**
`admin_bucket_create` with `confirm: true`.

**Verify**
- `admin_bucket_get` — quota, replica count, storage backend and compression are what you asked for, and
  `admin_cluster_info` — remaining cluster quota is still sane.
- `admin_stats_bucket` once traffic starts — resident ratio and memory used against quota.

**Rollback position**
- A brand-new empty bucket can simply be deleted (`admin_bucket_delete`, destructive). That is a clean
  rollback **only while it is empty**.
- Resizing later is `admin_bucket_update`, which is rated destructive: changing `ramQuota` or
  `replicaNumber` on a live bucket reshapes memory and moves data, and **lowering a quota below the
  working set evicts**. Size it right the first time.
- Once the application is writing, the point of no return has passed — deleting the bucket is data loss,
  not rollback.

## 5. Rotate a user credential

**Preconditions**
- `admin_whoami` — confirm this server is authenticating with enough privilege.
- `admin_user_get` on the target user — capture the **current role grants** before changing anything.
  `admin_user_create` is create-*or-update*, so a call that omits roles changes them.
- Know every consumer. The change is instantaneous, every holder of the old password fails at the moment it
  lands, and there is no overlap period — one password is valid at a time. Prefer a scheduled window.

**Dry run**
`admin_user_change_password` with `dry_run: true` (or `admin_user_create` with
`dry_run: true` if you are also adjusting roles). Check the previewed username — the
password itself is redacted from the preview, the logs and any error response, by design.

**Execute**
`admin_user_change_password` with `confirm: true`. If roles change too, use
`admin_user_create` with the **full** role string, not a partial one.

**Verify**
- `admin_user_get` — roles unchanged (or changed exactly as intended); have a consumer authenticate with
  the new credential.
- `admin_system_events` — the change is visible in the cluster event log. The server's own audit record
  names the tool, redacted arguments and outcome, plus the principal and mode on an authenticated session.

**Rollback position**
- Rollback is "set it back", which requires knowing the old password. If you do not have it, **there is
  no rollback** — you roll forward by distributing the new one.
- On Couchbase 8.0+, `admin_user_lock` / `admin_user_unlock` give a reversible way to take a credential
  out of service without deleting it. That is the safer move when the goal is "stop this credential being
  used" rather than "change its password".
- `admin_user_delete` has no rollback at all: the role grants are not recoverable from this server.

## 6. Stand up an XDCR replication

**Preconditions**
- The target cluster exists, is healthy, and the **target bucket already exists**.
- The remote hostname must satisfy `CB_ADMIN_EGRESS_ALLOWED_HOSTS`. XDCR is one of the operations where
  the *cluster* dials out, so a refusal here is policy, not a bug.
- `admin_xdcr_references_list` — a usable reference may already exist; do not duplicate it.
- Decide conflict resolution and whether a conflict log is wanted **before** creating the replication.
  Conflict logging is configured at creation with `conflictLogging=true` plus a `conflictLoggingMapping`
  naming the target bucket/scope/collection, and it is **Couchbase 8.0+ only**.

**Dry run**
`admin_xdcr_reference_create` with `dry_run: true`, then `admin_xdcr_replication_create`
with `dry_run: true`. Confirm the previewed source bucket, target reference and target bucket. This is
the call where a wrong target streams a bucket into the wrong cluster.

**Execute**
1. `admin_xdcr_reference_create` with `confirm: true`.
2. `admin_xdcr_replication_create` with `confirm: true`.

**Verify**
- `admin_xdcr_replications_list` — the replication exists and is active; `admin_stats_bucket` on the target
  — item count is climbing toward the source.
- On 8.0+ with conflict logging configured, `admin_xdcr_conflict_log_query` reads the conflict log
  collection.

**Rollback position**
- After step 1 only: clean. `admin_xdcr_reference_delete` removes an unused reference (it refuses while
  active replications exist, which is the behaviour you want).
- **Step 2 is the point of no return for the target's contents.** The moment the replication starts,
  documents are written into the target bucket. Deleting the replication
  (`admin_xdcr_replication_delete`) stops further writes but **does not remove what was already
  replicated**. If the target was wrong, the cleanup is a data problem in that cluster, not a rollback
  here.
- `admin_xdcr_replication_pause` is the reversible control: it stops the stream and preserves the
  replication, and `..._resume` continues it.

## 7. Deploy an Eventing function

**Preconditions**
- Source bucket/scope/collection and every bound keyspace exist. `admin_eventing_list` and
  `admin_eventing_status` — is a function of this name already present, and in what state.
- The `definition` is complete: `appname`, `appcode`, `depcfg` (source keyspace plus bindings), `settings`.
- Understand what the code *does* on deploy: it processes mutations immediately, including side effects on
  other collections or external systems. Eventing memory quota is adequate (`admin_cluster_info`).

**Dry run**
`admin_eventing_create_or_update` with `dry_run: true`, then `admin_eventing_deploy` with
`dry_run: true`. Confirm the previewed `appname` and source keyspace — deploying against
the wrong source is the expensive mistake.

**Execute**
1. `admin_eventing_create_or_update` with `confirm: true` — creates or **replaces** the function
   definition.
2. `admin_eventing_deploy` with `confirm: true`. Returns a task id.

**Verify**
- `admin_eventing_status` — composite state reaches `deployed`. `admin_eventing_stats` — processing rates,
  failure counts, latency percentiles, DCP backlog; a rising failure count means stop and undeploy.
- Check the downstream effect the function is supposed to have.

**Rollback position**
- After step 1, before deploy: clean if the function is new (delete it), **not clean if it replaced an
  existing function** — create-or-update overwrites the previous definition, and this server does not
  keep the old one. Capture `admin_eventing_get` output first if a function of that name already exists.
- After deploy: **the side effects the function has already produced are the point of no return.**
  Undeploying stops processing but does not undo writes it made.
- The reversible control is **pause**, not undeploy: `admin_eventing_pause` preserves the checkpoint and
  `admin_eventing_resume` continues from it. `admin_eventing_undeploy` **discards the checkpoint** — the
  function can be redeployed, but mutations that occurred while it was undeployed are not replayed.

## 8. Run and verify a backup

**Preconditions**
- The Backup Service must be running on at least one node.
- `admin_backup_repository_list` — does a suitable repository already exist.
- If one must be created: `admin_backup_plans_list` first, because a repository must name a plan
  (built-ins include `_daily_backups` and `_hourly_backups`), and you need an archive path the **backup
  service** can write — a path inside the service's own filesystem, not the caller's.

**Dry run**
`admin_backup_repository_create` (if needed) and `admin_backup_run` with `dry_run: true`.
Confirm the repository name in the preview.

**Execute**
1. `admin_backup_repository_create` with `confirm: true`, if required.
2. `admin_backup_run` with `confirm: true`. It is asynchronous and returns a task id.

**Verify**
- `admin_cluster_tasks` — the backup task progresses and completes; `admin_backup_list` on the repository
  — the new backup is present.
- Optionally record it: `cb_backup_catalog_record` stores tags and a pointer (it copies no data and creates
  no backup), and `cb_backup_catalog_sync` later marks entries present, missing or unchecked.
- **A backup is not verified until a restore has been tested.** Test restores into a scratch cluster,
  never into the cluster you are protecting.

**Rollback position**
- Taking a backup has nothing to roll back; the cost is I/O and archive space.
- Restore is the dangerous half. `admin_backup_restore_run` **overwrites data in the target cluster** and
  is the only tool in this family that destroys anything. Its point of no return is the moment it starts:
  there is no undo, and the only recovery is another restore from a different backup — which requires
  that a different backup exists.
- `cb_backup_catalog_delete` removes a catalogue **entry**, never the backup itself.

## 9. Turn on encryption at rest

**Preconditions**
- `admin_encryption_get` — read the cluster's **current** configuration. Field names vary by version; 7.x
  has partial DARE support and 8.x has first-class configuration. Do not assume a shape.
- Decide `keySource` (`master_password` or `kmip`), `algorithm` and `rotateInterval`.
- If KMIP: the KMIP server is reachable **from the cluster nodes**, certificates are in place, and the
  key UID exists. `admin_kmip_get` shows the current configuration and connection status. The KMIP
  hostname must satisfy the egress allowlist.
- Plan a maintenance window that includes a **restart test**, because that is where a wrong key source
  actually fails.

**Dry run**
`admin_kmip_set` with `dry_run: true` first (if using KMIP), then `admin_encryption_set`
with `dry_run: true`. Read the previewed host, port, certificate paths and key UID character by
character.

**Execute**
1. `admin_kmip_set` with `confirm: true`, if `keySource` is `kmip`.
2. `admin_encryption_set` with `confirm: true`.

**Verify**
- `admin_kmip_get` — connection status is healthy. `admin_encryption_get` — enabled state, algorithm, key
  source and rotation status match intent. `admin_system_events` for the corresponding cluster events.
- **Restart one node in the window and confirm it comes back and serves data.** A broken key source only
  manifests at restart.

**Rollback position**
- Before either write: full.
- After `admin_kmip_set`: you can point it back, *provided the cluster is still running and can still
  reach a working key source*. Once a node restarts with an unreachable or wrong master key, **the
  cluster cannot decrypt its own data** and this server cannot fix it — that is the point of no return,
  and recovery is a Couchbase support matter.
- After `admin_encryption_set` with data already encrypted: disabling encryption is a separate operation
  with its own cost and is not a rollback. Misconfiguration here can render data unreadable.
- Both tools belong in `CB_ADMIN_ALWAYS_CONFIRM` on any production server.

## 10. Provision a Capella project, cluster, credential and CIDR

This is the control plane, not a cluster: `capella_*` tools authenticate with an organization API key,
not cluster credentials.

**Preconditions**
- `capella_guardrails_status` **first.** It reports the pinned organization, allowlisted projects, required
  name prefix, environment ceiling and default TTL, from the code that enforces the policy — and explains
  any later refusal.
- `CAPELLA_API_KEY_SECRET` configured; `capella_organizations_list` is the cheapest call that proves the
  token is valid.
- Know the client address you will allowlist: a `/32`, with `expiresAt` set so a temporary rule cannot
  outlive its purpose. Never `0.0.0.0/0`.
- Cluster names must satisfy `CAPELLA_ENV_NAME_PREFIX` — the prefix is what makes the cluster reapable
  later.
- **Note the asymmetry:** `CAPELLA_ALLOWED_PROJECTS` unset means the server will *create* but refuse to
  *delete*. Provisioning can succeed into a configuration where teardown is impossible from here.

**Dry run**
Each of `capella_project_create`, `capella_cluster_create`, `capella_bucket_create`,
`capella_database_credential_create` and `capella_allowed_cidr_create` accepts
`dry_run: true`. Preview the whole sequence and check the project id, cluster name prefix
and CIDR before any of it runs.

**Execute — sequentially, because each step needs the previous one's id**
1. `capella_project_create` — a dedicated project is the natural boundary, and it is the unit the
   guardrail allowlist works on.
2. `capella_cluster_create` — asynchronous, and slow. `configurationType` (`singleNode` / `multiNode`) is
   **immutable after creation**; so is the App Service version if you add one. Preserve any
   `mcp-env:{...}` marker in the description.
3. Poll `capella_cluster_get` until the state is terminal. Terminal states include `healthy`,
   `turnedOff`, `degraded`, `deploymentFailed` and `destroyFailed`; in-flight states include `deploying`,
   `scaling`, `rebalancing` and `upgrading`. Treat an unrecognized state as in-flight and wait.
4. `capella_allowed_cidr_create` — with `expiresAt`.
5. `capella_bucket_create` — fast, seconds, unlike cluster creation.
6. `capella_database_credential_create` — **if `password` is omitted, Capella generates one and returns
   it in that response only. It cannot be retrieved later. Capture it now.**

For a throwaway test environment, prefer `capella_env_ensure` over driving these individually: it reconciles
the whole sequence, is safe to call repeatedly, reuses existing resources, and returns
`{phase, done, retry_after_s}` so a caller polls instead of blocking. Then `capella_env_connection_info` for
what a client needs to connect, and `capella_env_status` to poll without risking a write.

**Verify**
- `capella_cluster_get` — state `healthy`. `capella_allowed_cidrs_list` — the entry is present, correctly
  scoped, with its expiry. `capella_database_credentials_list` — the credential has the intended access.
- Connect from the allowlisted client with the captured password, then `capella_events_list` /
  `capella_project_events_list` for the control-plane record.

**Rollback position**
- Each step is individually reversible *if the guardrails permit deletion*: project, cluster, bucket,
  credential and CIDR all have delete operations, and deletion is refused unless the resource is in an
  allowlisted project, carries the configured name prefix, is not in `CAPELLA_PROTECTED_CLUSTERS`, and
  Capella's own deletion protection is off. **Ordering matters: App Service before cluster.**
- **If `CAPELLA_ALLOWED_PROJECTS` is unset, there is no rollback through this server at all** — it fails
  closed on deletion. You created something you cannot remove from here. Check
  `capella_guardrails_status` *before* provisioning, not after.
- `configurationType` and App Service version are immutable: changing them means deleting and recreating,
  which is destruction, not rollback.
- A generated credential password that was not captured is unrecoverable. The only path is to delete and
  recreate the credential — and `capella_database_credential_update` replaces the `access` grants rather
  than merging them, so read the current grants with `capella_database_credential_get` before any update.
- For managed environments, `capella_env_teardown` does the ordering correctly, and `capella_env_reap`
  cleans up expired ones — its own `dry_run` defaults to **true**, so a reap that reports what it would
  delete and deletes nothing is working as designed.
