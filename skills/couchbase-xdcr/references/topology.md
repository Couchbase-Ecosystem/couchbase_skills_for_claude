# XDCR topology

## Contents

- [The only primitive is a unidirectional replication](#the-only-primitive-is-a-unidirectional-replication)
- [Active-passive (unidirectional)](#active-passive-unidirectional)
- [Active-active (bidirectional)](#active-active-bidirectional)
- [Ring and multi-cluster topologies](#ring-and-multi-cluster-topologies)
- [XDCR within a single cluster](#xdcr-within-a-single-cluster)
- [Topology decision checklist](#topology-decision-checklist)
- [Collection-aware replication](#collection-aware-replication)
- [Active-active XDCR with Sync Gateway (mobile)](#active-active-xdcr-with-sync-gateway-mobile)
- [The user xattr limit — read before promising active-active with mobile](#the-user-xattr-limit--read-before-promising-active-active-with-mobile)
- [Auditing xattrs on a document](#auditing-xattrs-on-a-document)
- [vBucket count constraints](#vbucket-count-constraints)
- [Transactions and XDCR](#transactions-and-xdcr)
- [Bandwidth planning](#bandwidth-planning)

## The only primitive is a unidirectional replication

XDCR provides exactly one mechanism: a unidirectional replication from a source bucket to a target bucket, driven by an XDCR agent on the source using the Database Change Protocol. Every topology is composed from those. There is no distinct "bidirectional replication" object — bidirectional is two unidirectional replications in opposite directions between the same pair of buckets.

Source and target may be Couchbase or Ephemeral buckets. Note that an Ephemeral bucket configured to eject data when its RAM quota is exceeded is not a safe XDCR source: not all data written to it is guaranteed to be replicated.

Source: [XDCR overview](https://docs.couchbase.com/server/current/learn/clusters-and-availability/xdcr-overview.html)

## Active-passive (unidirectional)

```
Cluster A (primary) ──XDCR──► Cluster B (DR / read replica)
```

Writes always go to A. B is eventually consistent behind A by the replication lag. The documentation's framing is that the replicated data on B is principally a backup supporting disaster recovery, even though it can serve reads.

**When to use:** disaster recovery, read offload to a secondary region, workload isolation.

**Conflict risk:** none in steady state, because there is only one write path. Conflicts become possible during a failover scenario where B starts accepting writes and A later returns.

## Active-active (bidirectional)

```
Cluster A ◄──XDCR──► Cluster B
```

Two replications. Both clusters accept writes; same-key writes on both sides before replication catches up produce a conflict, resolved automatically by the buckets' conflict resolution policy.

**When to use:** low-latency local writes from multiple geographies; no single point of write failure.

**Mitigations, in order of effectiveness:**

1. **Partition the key space by region** so the same key is never written in two places — `eu::user::<id>` written only in EU, `us::user::<id>` only in US. This eliminates conflicts by construction and is the only approach that actually guarantees no lost writes.
2. **Partition by collection** and replicate each collection in one direction only, even inside an otherwise active-active pair.
3. **Enable Conflict Logging (8.0+)** so conflicts are recorded and can be reconciled by an application workflow. This does not prevent a version from losing; it makes the loss visible.
4. **Accept automatic resolution** for data where "one of these two writes survives" is genuinely acceptable — session state, presence, non-critical preferences.

**Do not use active-active for:**

- Counter or increment semantics. Both sides incrementing the same document will conflict, and one increment is discarded.
- Workflows requiring cross-region transactional consistency. Couchbase's own transactions documentation advises against active-active bidirectional replication with transactions; see below.

## Ring and multi-cluster topologies

The documented example of a complex topology is a **ring**: multiple clusters each connected to exactly two peers so a complete ring of connections is formed. Hub-and-spoke and chain shapes are also just combinations of unidirectional replications, but they are not named or given special support in the documentation — do not present them as product features.

Two practical consequences for any topology with more than two clusters:

- Conflict Logging must be enabled on **every leg**. A three-cluster ring with bidirectional links has six legs, and a conflict can arise on any of them.
- If you use cross cluster versioning, `enableCrossClusterVersioning` must be `true` on **every bucket in the topology**, and `versionPruningWindowHrs` must be set to the **same value** on all of them. XDCR does not validate this for you.

Latency accumulates along a path, so a document written at one end of a chain is visible at the other only after the sum of the hops.

## XDCR within a single cluster

XDCR can name the same cluster as both source and target, as long as the source and target buckets are different. Useful for bucket-to-bucket data shaping without a second cluster.

## Topology decision checklist

| Requirement | Topology |
|---|---|
| DR only, writes always from one region | Active-passive |
| Multi-region reads with central writes | Active-passive plus read routing |
| Multi-region writes, keys partitioned by region | Active-active |
| Multi-region writes, conflicts genuinely unacceptable | Reconsider. Active-active cannot guarantee this; partition the key space, or fall back to partitioned active-passive |
| Multi-region writes plus auditability of lost writes | Active-active with Conflict Logging (8.0+, needs ECCV) |
| Global reference data pushed out to regions | Unidirectional from the authoritative cluster to each region |
| Mobile/Sync Gateway on both sides | Active-active with Sync Gateway — see below, and check the xattr limit first |

## Collection-aware replication

By default XDCR uses **implicit mapping**: a source collection replicates to the target collection with the identical `scope-name.collection-name` path.

Two alternatives, set on the replication and **mutually exclusive**:

- `collectionsExplicitMapping=true` with `colMappingRules` — replicate only the collections named in the rules, optionally to differently named targets. Implicit bucket-level mapping is then switched off entirely.

  ```json
  { "inventory.airline": "inventory.MyAirline" }
  ```

- `collectionsMigrationMode=true` with `colMappingRules` — route documents out of the source bucket's **default collection** into target collections chosen by filter expressions.

  ```json
  { "city=\"San Francisco\"": "California.SanFrancisco" }
  ```

Use explicit mapping to reduce bandwidth, rename on the way across, or keep internal collections out of the replication. Because implicit mapping is off, **a source collection missing from `colMappingRules` is silently not replicated** — audit the rules against the live collection list whenever collections are added.

Source: [Creating XDCR Replications](https://docs.couchbase.com/server/current/rest-api/rest-xdcr-create-replication.html)

## Active-active XDCR with Sync Gateway (mobile)

Combining XDCR with Sync Gateway in a bidirectional topology is supported only above specific versions. Below them, **only active-passive is supported, and a bidirectional setup can cause data corruption.**

- Minimum **Couchbase Server 7.6.6** and **Sync Gateway 4.0.0**.
- `enableCrossClusterVersioning` must be `true` on **every** bucket in the replication topology.
- Each replication in the topology is created or updated with `mobile=Active` (the default is `Off`). Both directions must be set.
- The inbound user needs the **XDCR Inbound** and **Data Writer** RBAC roles.
- Sync Gateway 4.0 moves from revision trees to version vectors and resolves automatically with Last-Write-Wins using hybrid logical clocks. For active-active DR, both clusters are configured with `import_docs=true`.
- Eventing functions that write to XDCR-replicated buckets can create "ping-pong" replication loops in a bidirectional topology. Add guards so a function does not re-trigger itself across the link.

Sources: [XDCR Active-Active with Sync Gateway](https://docs.couchbase.com/server/current/learn/clusters-and-availability/xdcr-active-active-sgw.html), [XDCR — Server Compatibility](https://docs.couchbase.com/sync-gateway/current/server-compatibility-xdcr.html)

## The user xattr limit — read before promising active-active with mobile

This is a hard, documented limitation with a silent failure mode.

> If you use the user created extended attributes (user xattrs) in your documents, and you have **more than 10 user xattrs in a document**, then you **cannot use the feature XDCR Active-Active with Sync Gateway**. This is due to an internal limitation of managing extended attributes in a document. If you try to use the feature XDCR Active-Active with Sync Gateway when you have more than 10 user xattrs in your document, **the XDCR replication silently skips replicating that document.** As a result, the data in the replication-skipped document will not be consistent between the target and source clusters. The only way you will know this skip occurred is because the Prometheus stat `subdoc_cmd_docs_skipped` will be incremented and the document will not be consistent between the target and source.

— [XDCR Active-Active with Sync Gateway](https://docs.couchbase.com/server/current/learn/clusters-and-availability/xdcr-active-active-sgw.html)

Points to be precise about with customers:

- The threshold is **more than 10 user xattrs**, counting user-created extended attributes only, not system xattrs such as `_vv` or `_sync`.
- The documented scope of the limitation is **XDCR Active-Active with Sync Gateway** (`mobile=Active`). The documentation does not extend this statement to plain active-active XDCR without Sync Gateway; do not generalise it beyond what is written, and do not assume plain active-active is safe at >10 either — confirm with Couchbase for that case.
- The failure is **silent**: no replication error, no paused replication, no per-document warning. The document is simply skipped and the two clusters diverge on it.
- The **only** signal is the Prometheus stat **`subdoc_cmd_docs_skipped`** incrementing. Alert on it before enabling `mobile=Active` in any deployment that uses user xattrs at all.
- Because the failure is per-document, a fleet can be healthy for months and then diverge the moment an application starts writing an eleventh xattr.

**What to do before enabling it:** inventory user xattr usage across the dataset, cap the application at a documented maximum well below 10, and wire `subdoc_cmd_docs_skipped` into alerting. If a framework or library on the same documents also writes xattrs (mobile, an ORM, a CDC tool), count those too.

## Auditing xattrs on a document

Two mechanisms, with different reach — this matters when you are trying to answer "how many user xattrs does this document actually have?"

**KV sub-document with the `$XTOC` virtual xattr — the authoritative way to enumerate.**
`$XTOC` is a server-defined virtual extended attribute that, when used as a sub-document search path, **returns the list of extended attribute names on the document**. It is accessed through the sub-document API from an SDK (or a tool that speaks it), not from SQL++. This is the mechanism to use when you need the count and names of xattrs on a document. There is also `$document`, which returns document metadata (expiry, CAS, seqno, datatype, value size, last modified). ([Extended Attributes](https://docs.couchbase.com/server/current/learn/data/extended-attributes-fundamentals.html))

**SQL++ `META().xattrs` — for reading known attributes, not for enumeration.**
`META().xattrs` is documented as a `META()` property in the **Couchbase Server 8.0** SQL++ reference; it is not present as a `META()` property in the 7.1, 7.2, or 7.6 reference pages. The syntax is `META().xattrs.<attribute>[.<path>]`. Constraints that matter here:

- **Selecting the entire `META().xattrs` object returns an empty result.** You must name the attribute. So SQL++ cannot be used to discover which xattrs exist on a document — only to read ones you already know the names of.
- You can index a specific attribute (`META().xattrs.attr1`) but not the whole `META().xattrs` object.
- Starting with 8.0 you can include **up to 15 XATTRs per query**, and 8.0 also adds the ability to modify xattrs from `INSERT`, `UPSERT`, and `UPDATE`.
- `META().xattrs` can reach virtual xattrs, but the documentation calls this an expensive operation that may increase query latency.
- Separately, on **7.6.2 and later**, `META()` can be combined with `SEARCH()` to return xattr data through the Search Service when no suitable Search index exists for the query.

([META function](https://docs.couchbase.com/server/current/n1ql/n1ql-language-reference/metafun.html), [What's New in 8.0](https://docs.couchbase.com/server/current/introduction/whats-new.html))

**Practical audit recipe:** enumerate names per document with a KV sub-document `get` on `$XTOC` (works on 7.x and 8.x), and use SQL++ `META().xattrs.<name>` on 8.0+ only to read or filter on attributes you already know about.

Note also that extended attributes count against the 20 MB maximum document size, and XDCR filtering expressions can match on them via `META().xattrs.<name>`.

## vBucket count constraints

Couchbase Server versions **before 8.0 do not support XDCR between buckets with different numbers of vBuckets**, and do not support Magma buckets with 128 vBuckets. Since 8.0 makes Magma with 128 vBuckets the default storage engine for new Enterprise Edition buckets, this bites during mixed-version rollouts:

- You **cannot** replicate from a pre-8.0 cluster to a Magma 128-vBucket bucket.
- You **can** replicate from a Magma 128-vBucket bucket on 8.0+ to a pre-8.0 cluster, because 8.0 Magma buckets can replicate to buckets with a different vBucket count — but bidirectional replication is then impossible, so avoid the configuration.

## Transactions and XDCR

XDCR gives eventual consistency for transactional changes. Uncommitted changes are never sent; once committed, the changes arrive **one by one**, so a connection lost mid-stream can leave the target holding a partial transaction. Document counts also differ between source and target because transaction metadata documents are never replicated.

Couchbase's documentation advises **against** using active-active bidirectional replication with transactions. If it is unavoidable, transactions must not touch the same set of documents on both clusters: each cluster's applications own a mutually exclusive, key-identified set of documents, and a failed transaction is retried **on the same cluster**. Use timestamp-based conflict resolution, and follow the documented safe-failover steps. ([Transactions](https://docs.couchbase.com/server/current/learn/data/transactions.html))

## Bandwidth planning

Replication traffic is driven by mutation rate times average document size, plus protocol and metadata overhead, doubled for a bidirectional pair. Compression (`compressionType`) reduces the wire volume when the target supports it. `networkUsageLimit` caps mutation bandwidth for the entire cluster in MB/s; the per-node limit is that value divided by the node count, and it does not cover topology or statistics traffic.

If cross cluster versioning is enabled, add the HLV metadata per document: **109 + 40N bytes**, where N is the number of buckets mutating the document in the replication topology. That size stays constant while the topology does; it grows when the topology changes or a document copy passes through additional clusters, and is trimmed back by periodic pruning governed by `versionPruningWindowHrs` (default 720 hours / 30 days).

For detailed sizing, see `couchbase-sizing/references/network.md`.
