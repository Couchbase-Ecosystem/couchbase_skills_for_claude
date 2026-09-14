---
name: couchbase-upgrade
description: "Plan and execute Couchbase Server version upgrades, including the supported upgrade paths to 8.0 and the breaking changes it introduces. Use whenever the user asks about upgrading Couchbase, rolling or online upgrade, swap rebalance upgrade, offline upgrade, graceful failover with delta recovery, upgrade path from 7.x to 8.0, upgrade checklist, mixed-mode feature availability, cluster compatibility, the Magma storage engine becoming the default in 8.0 Enterprise Edition, the 128 vBucket default, memcached bucket removal, Community to Enterprise Edition upgrades, pre-upgrade backup, post-upgrade verification, or 'how do I upgrade Couchbase without downtime.' Distinct from couchbase-mcp, which covers the MCP tool sequence for executing an upgrade; this skill covers planning, compatibility, and the 8.0-specific changes to handle before and after those steps."
license: Apache-2.0
---

# Couchbase Upgrade

Planning and executing Couchbase Server version upgrades — upgrade paths, upgrade procedures, breaking changes, and pre/post-upgrade steps.

Distinct from the rolling upgrade section in `couchbase-mcp` (which covers the MCP tool sequence for executing the upgrade). This skill covers the *planning* layer: what to check before you run those tools.

**Current release at the time of writing:** Couchbase Server 8.0.3 (September 2026). 8.0.0 was released October 2025. Always confirm the current patch against the [8.0 release notes](https://docs.couchbase.com/server/current/release-notes/relnotes.html) before planning — the upgrade path table is patch-specific.

## When this skill applies

- "How do I upgrade from 7.x to 8.0?"
- "What changed in 8.0 that could break my cluster?"
- "What's the safe upgrade path?"
- "Which upgrade procedure should I use?"
- "What can't I use during a mixed-version upgrade?"
- "How do I verify the upgrade worked?"

## Supported upgrade paths

Couchbase does not support upgrading between non-adjacent versions. Every path to 8.0 goes through an intermediate release. The paths below are the ones documented for 8.0.1 and are the same for Enterprise and Community Edition — **check the current upgrade page for your exact target patch before you plan the work.**

| Starting version | Documented path to 8.0.x |
|---|---|
| 5.0.x / 5.1.x / 5.5.x | → 6.6 → 7.2.3 → latest 7.2.x → 8.0.x |
| 6.0.x / 6.5.x | → 6.6 → 7.2.3 → latest 7.2.x → 8.0.x |
| 6.6.x | → 7.2.3 → latest 7.2.x → 8.0.x |
| 7.0.x / 7.1.x | → 7.2.3 → latest 7.2.x → 8.0.x |
| 7.2.x | → latest 7.2.x → 8.0.x |
| 7.6.x | → latest 7.6.x → 8.0.x |

**There is no direct 7.0 or 7.1 → 8.0 upgrade.** Plan the intermediate hop to 7.2.3 explicitly.

### Community Edition → Enterprise Edition

This is an edition change, not a version upgrade, and the two cannot be combined:

- Replacement EE nodes must run **the same version number** as the CE nodes they replace, or the upgrade may fail.
- To move from an earlier CE version to a later EE version, run **two separate upgrade procedures** — change edition at one version, then upgrade the version.
- An online CE → EE change is done by swap rebalance. Graceful failover with delta recovery is **not** supported for an edition change.
- A cluster must run entirely on one edition.

Source: https://docs.couchbase.com/server/current/install/upgrade.html

## Upgrade procedures

All supported upgrades can be performed with the cluster online or offline.

| Procedure | Downtime | Notes |
|---|---|---|
| **Swap rebalance at full capacity** | None | Spare nodes are added as upgraded nodes are removed. Data-serving capacity stays constant. Needs spare hardware. |
| **Swap rebalance with reduced capacity** | None | Nodes are removed, upgraded, and re-added in batches. No spare hardware needed; the cluster serves data at reduced capacity during the upgrade. |
| **Graceful failover with delta recovery** | None | Simplest and lowest-resource online option, but **only usable for nodes running the Data Service alone**. Not available for CE → EE. |
| **Cluster offline** | Full | All nodes down at once, no rebalance needed. Simplest procedure; requires a maintenance window. |

Single-node clusters are not a supported production topology; a development single-node upgrade has its own procedure.

Source: https://docs.couchbase.com/server/current/install/upgrade-procedure-selection.html

## Pre-upgrade checklist

- [ ] **Memcached buckets: remove them first (8.0+).** Memcached buckets were deprecated in 6.5.1 and removed in 8.0. The upgrade process **exits with an error** if any memcached bucket exists. Migrate that data to ephemeral buckets before starting.
- [ ] Full cluster backup (`cbbackupmgr`, the Backup Service, or Capella managed backup)
- [ ] Verify the cluster is healthy: all nodes `active` + `healthy`, no rebalance in progress, XDCR caught up (`changes_left` ≈ 0)
- [ ] Confirm the exact upgrade path for your source patch against the current upgrade docs
- [ ] Upgrade to the latest patch of your current release before moving to the next release — the documented paths themselves route through "latest 7.2.x" / "latest 7.6.x"
- [ ] Review the release notes for the target patch, including deprecated and removed items
- [ ] Check SDK compatibility (see below)
- [ ] Test the upgrade on a staging cluster first
- [ ] Confirm which upgrade procedure applies to each node's service set (delta recovery is Data-only)

## Couchbase 8.0: what actually changed

**1. Memcached buckets removed**

Deprecated in 6.5.1, fully removed in 8.0.0. This is a hard blocker: the upgrade fails if one is present. Ephemeral buckets are the replacement.

**2. Magma with 128 vBuckets is the default storage engine (8.0+, Enterprise Edition only)**

Per the docs: "If you do not specify a storage engine for a new Couchbase bucket, Couchbase Server Enterprise Edition 8.0 uses Magma with 128 vBuckets as the storage engine."

Impact:
- **Existing buckets are unchanged** — they keep the storage engine and vBucket count they were created with.
- **New buckets created after the upgrade** default to Magma/128 unless you specify otherwise.
- If deployment scripts or IaC templates assume 1024 vBuckets or Couchstore, set `storageBackend` and `numVBuckets` explicitly rather than relying on the default.
- Community Edition is unaffected — Magma is EE only, so CE continues to create Couchstore buckets with 1024 vBuckets.

vBucket count cannot be changed after bucket creation. See `couchbase-magma` for how to choose.

**3. Features gated during mixed mode**

While a cluster has nodes on more than one version, it runs in mixed mode. The docs are explicit: such features "should not be used during the upgrade process, unless such use is explicitly supported in mixed-mode conditions." Documented as not usable in mixed mode:

- **Magma** — "Magma should not be switched on until all nodes have been upgraded"
- Scopes and Collections (on an upgrading cluster, documents on an upgraded node appear in the `_default` collection)
- The Backup Service
- Cost-Based Optimizer, SQL++ transactions, and User-Defined Functions
- On-the-wire security features introduced in 7.0

All features of the higher version become available once cluster upgrade is complete. Check the feature-availability page for your specific source and target versions — the list is version-pair specific.

Source: https://docs.couchbase.com/server/current/install/upgrade-feature-availability.html

**4. Enterprise Edition gating on 8.0 features**

Several 8.0 capabilities are Enterprise Edition only, including the Magma storage engine and the new Index Service vector index types (Hyperscale and Composite Vector indexes). Community Edition clusters upgrade to 8.0 normally but do not get these. Confirm your edition before planning around any of them.

**5. Index Service RAM planning for vector indexes**

8.0 adds Hyperscale and Composite Vector indexes in the Index Service, alongside the existing Search Service vector indexes. These consume Index Service RAM quota. If the Index Service is already close to its quota, size for the additional RAM before building vector indexes post-upgrade. Do not assume a fixed overhead figure — measure on a staging cluster with representative data.

**6. Removed and deprecated interfaces to check in tooling**

- `cbepctl`: `warmup_min_items_threshold` and `warmup_min_memory_threshold` removed
- `mcstat`: multiple stat groups in one invocation, and `--json=pretty`, removed
- Bucket priority removed from the UI (REST/CLI retained for compatibility)
- Deprecated: `GET /pools/default/buckets/[bucket]/stats` and the per-destination XDCR stats endpoint, both replaced by newer endpoints
- Metric renames: "Cache Miss Ratio" → "Get Miss Ratio"; `kv_vb_ht_memory_bytes` → `kv_vb_ht_memory_overhead`

Grep your monitoring config and automation for these before upgrading.

Source: https://docs.couchbase.com/server/current/release-notes/relnotes.html

## Online upgrade sequence (summary)

The MCP tool sequence is in `couchbase-mcp` (operational-runbooks reference). The shape of a swap-rebalance upgrade:

1. Confirm a current backup exists and the cluster is healthy
2. Prepare an upgraded spare node (or plan the reduced-capacity batch)
3. Add the new node and remove an old node in the **same** rebalance (this is what makes it a swap)
4. Wait for rebalance to complete and verify node health
5. Repeat until every node is on the target version
6. Confirm all nodes report the target version and the cluster is no longer in mixed mode before enabling any version-gated feature

For Data-only nodes, graceful failover → upgrade → **full or delta recovery** → rebalance is the lower-resource alternative. Delta recovery is not valid for an edition change.

**Capella:** upgrades are delivered as maintenance jobs, not something you execute. Optional jobs are self-service scheduled; mandatory jobs are initiated by Capella Support. Couchbase aims to give 1–2 weeks' notice for critical upgrades followed by a 2–4 week upgrade window. Free tier clusters are upgraded at Couchbase's convenience. You schedule the window; you do not choose the target version.

Source: https://docs.couchbase.com/cloud/clusters/upgrade-cluster.html

## Post-upgrade verification

```python
# Verify all nodes healthy and on the target version
admin_cluster_details(cluster="prod")
# Check: every node shows the target version, clusterMembership=active, status=healthy

# Confirm the cluster is no longer in mixed mode (read the cluster compatibility version)
admin_cluster_info(cluster="prod")

# Confirm no upgrade-related task is still running
admin_cluster_tasks(cluster="prod")

# Run a smoke test query (data-plane MCP server)
run_sql_plus_plus_query(
    bucket_name="your-bucket",
    scope_name="_default",
    query="SELECT COUNT(*) AS c FROM `your-collection` WHERE type IS NOT MISSING",
)

# Verify XDCR is healthy if applicable
admin_xdcr_replications_list(cluster="prod")
admin_stats_multi(metrics=["xdcr_changes_left_total"], cluster="prod")
# Check: changes_left ≈ 0, no errors
```

Then re-check anything in the "removed and deprecated interfaces" list above that your dashboards or scripts depend on.

## SDK compatibility

Do not treat SDK compatibility as a single fixed minimum version — it is per-SDK and changes as versions reach end of life. The documented policy for the Java SDK is representative: "Server 7.6 & 8.0 are compatible with all supported (not yet End-of-Life) versions of the Java SDK, but for full support of the latest features you need to upgrade to a recent version of the SDK."

Practical guidance:

- Any SDK version still under support will connect to an 8.0 cluster for normal operations.
- 8.0-specific features (vector index types, newer APIs) need a recent SDK.
- Check the per-SDK compatibility matrix for your language and confirm your version is not EOL: https://docs.couchbase.com/java-sdk/current/project-docs/compatibility.html (equivalent pages exist for each SDK).
- Upgrade the cluster first, then the SDKs, unless an SDK you are on is already EOL.

## Related skills

- `couchbase-mcp` — rolling upgrade tool sequence (operational-runbooks reference), and the data-plane smoke-test query
- `couchbase-admin-mcp` — the `admin_cluster_*`, `admin_rebalance_*` and `admin_xdcr_*` tools the pre- and post-upgrade checks call
- `couchbase-backup-restore` — pre-upgrade backup procedure
- `couchbase-magma` — Magma storage engine behavior and the 128 vs 1024 vBucket decision
- `couchbase-ai-applications` — 8.0 vector index types available post-upgrade
- `couchbase-kubernetes` — rolling upgrades driven by the Autonomous Operator rather than by hand
- `couchbase-performance-tuning` — post-upgrade tuning, and the 8.0 metric renames that affect it
