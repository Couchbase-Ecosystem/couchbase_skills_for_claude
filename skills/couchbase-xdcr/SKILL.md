---
name: couchbase-xdcr
description: "Design and operate Couchbase XDCR (Cross Data Center Replication). Use whenever the user asks about XDCR, cross-datacenter replication, multi-region replication, active-active or active-passive replication, XDCR topology, remote cluster references, replications, XDCR filtering expressions, collection mapping, conflict resolution, sequence-number vs timestamp (LWW) resolution, cross cluster versioning, XDCR Conflict Logging, XDCR with Sync Gateway and mobile, xdcrDiffer, replication lag or changes_left, or 'how do I replicate data between clusters / regions.' Distinct from couchbase-app-integration (application-layer XDCR-aware patterns) and couchbase-migration-execution (one-time data migration). Use proactively for disaster recovery planning, multi-region active-active architecture, and XDCR performance diagnosis."
license: Apache-2.0
---

# Couchbase XDCR

A skill for *designing and operating* Cross Data Center Replication between Couchbase clusters.

Distinct from:
- `couchbase-app-integration` — application code patterns for XDCR-aware reads and writes
- `couchbase-migration-execution` — one-time migration, not ongoing replication

## Edition gating — read this first

**XDCR is an Enterprise Edition feature.** From Couchbase Server 7.0, XDCR is commercial-only; Community Edition administrators do not get it. Never design an XDCR topology for a Community Edition deployment. ([XDCR overview](https://docs.couchbase.com/server/current/learn/clusters-and-availability/xdcr-overview.html))

## When this skill applies

- "How do I replicate between two clusters?"
- "Active-active vs active-passive — which should I use?"
- "How does conflict resolution work, and can I change the mode later?"
- "How do I filter which documents get replicated?"
- "What is XDCR Conflict Logging and how do I turn it on?"
- "How do I run active-active XDCR with Sync Gateway?"
- "XDCR replication is behind — how do I diagnose it?"

## Pick the right reference

| Question | Read |
|---|---|
| "Active-active vs active-passive — topology decision, ring topologies, mobile interop, the xattr limit" | `references/topology.md` |
| "How do I create references and replications, filter documents, map collections, tune throughput?" | `references/configuration.md` |
| "Conflict resolution modes, cross cluster versioning, Conflict Logging" | `references/conflict-resolution.md` |
| "Replication is lagging / erroring / counts don't match" | `references/troubleshooting.md` |

## Four core principles

**Principle 1 — Active-active means accepting eventual consistency and conflict potential.**
In bidirectional XDCR, both clusters accept writes independently. When the same document is written on both sides before replication catches up, a conflict occurs and one version is discarded. Couchbase resolves it automatically — by sequence number by default, or by timestamp (LWW) if the buckets were created that way. From 8.0 you can **log** conflicts so they are auditable, but logging does not change which version wins. If you cannot accept a discarded write for some data, that data does not belong in an active-active keyspace.

**Principle 2 — XDCR is bucket-to-bucket, and only unidirectional replications exist.**
A replication runs from one source bucket to one target bucket. Bidirectional is two unidirectional replications pointed at each other; ring and other topologies are built the same way. Five buckets means five replication definitions per direction. This is where DR coverage gaps come from — audit the replication list against the bucket list, not against intent.

**Principle 3 — Conflict resolution mode is fixed at bucket creation.**
The policy is a bucket property chosen when the bucket is created and **cannot be changed afterwards**. Source and target buckets must use the **same** policy — XDCR refuses to create a replication between buckets with different conflict resolution policies. Decide before you create the bucket.

**Principle 4 — Filtering early costs less than filtering late.**
A filter expression reduces bandwidth and target load. Define it at creation time. Changing a filter on a running replication may restart it from the checkpoint; the `filterSkipRestream` flag controls whether the replication restarts or continues. Either way, documents already delivered to the target are never un-replicated — a narrowed filter leaves stale documents behind on the target until you remove them.

## Version notes

- **7.x:** references and replications; collection-aware replication with explicit mapping and migration mode; filtering expressions; sequence-number and timestamp (LWW) conflict resolution; deletion filters.
- **7.6.6+:** the `enableCrossClusterVersioning` (ECCV) bucket property, which lets XDCR store Hybrid Logical Vector (HLV) metadata in the `_vv` xattr. Prerequisite for the mobile and Conflict Logging features below. Minimum Server version for active-active XDCR with Sync Gateway (with SGW 4.0.0+), set per replication with `mobile=Active`.
- **8.0:** **XDCR Conflict Logging** — conflicts are written as records into a conflict log collection you nominate. Also: identification of **incoming replications** on a cluster, the **xdcrDiffer** utility shipped in the installation package (previously built from source), and `genericServicesLogLevel`. 8.0 also relaxes the constraint that source and target buckets must have the same vBucket count. ([What's New in 8.0](https://docs.couchbase.com/server/current/introduction/whats-new.html))

There is **no custom JavaScript conflict resolution function** in Couchbase Server 8.0. The documented conflict resolution policies remain sequence number and timestamp. If someone asks for programmable merge logic, the honest answer is Conflict Logging plus an application-side reconciliation workflow.

## Managing XDCR

XDCR is managed through Couchbase Web Console, `couchbase-cli` (`xdcr-setup`, `xdcr-replicate`), or the REST API — in three stages: create a remote cluster **reference**, create and start a **replication**, then **monitor** it (pausing and resuming as needed).

The official Couchbase MCP server (`couchbase/mcp-server-couchbase`, https://mcp-server.couchbase.com/) is a data-plane server, **read-only by default** (`CB_MCP_READ_ONLY_MODE`), and does not expose XDCR administration. Use it to inspect documents on both sides when verifying replication fidelity; use the CLI, REST API, or UI to configure XDCR.

## Related skills

- `couchbase-app-integration` — application code for XDCR-aware reads, write conflicts, and active-active patterns
- `couchbase-sizing` — bandwidth and capacity planning
- `couchbase-mobile` — Sync Gateway, which has its own constraints when combined with active-active XDCR
- `couchbase-admin-mcp` — creating remote cluster references and replications through the admin MCP server
- `couchbase-backup-restore` — point-in-time recovery, which replication does not provide
- `couchbase-eventing` — functions writing into replicated buckets, a source of replication loops
- `couchbase-observability` — alert thresholds and metric definitions for `xdcr_changes_left_total` and replication failures
- `couchbase-transactions` — multi-document ACID semantics, which Couchbase advises against combining with active-active XDCR
