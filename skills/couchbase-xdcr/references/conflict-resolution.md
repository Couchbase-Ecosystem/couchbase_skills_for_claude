# XDCR conflict resolution

## Contents

- [What a conflict is](#what-a-conflict-is)
- [The two conflict resolution policies](#the-two-conflict-resolution-policies)
- [The policy is fixed at bucket creation](#the-policy-is-fixed-at-bucket-creation)
- [Cross cluster versioning and the Hybrid Logical Vector](#cross-cluster-versioning-and-the-hybrid-logical-vector)
- [XDCR Conflict Logging (8.0+)](#xdcr-conflict-logging-80)
- [There is no custom conflict resolution function](#there-is-no-custom-conflict-resolution-function)
- [Minimising conflicts](#minimising-conflicts)

## What a conflict is

A conflict occurs when the same document key is written on two clusters before those writes replicate to each other. When replication delivers the remote write, local and remote versions have diverged and one must win.

In active-passive (unidirectional) XDCR, conflicts arise only if the target is written to directly — for example during or after a failover.

## The two conflict resolution policies

Couchbase Server documents **two** conflict resolution policies:

**Sequence number-based (the default).** The document with the higher sequence number wins. If sequence numbers are equal, the comparison falls through to CAS value, then expiration (TTL), then document flags. Deterministic, but it reflects mutation count on each side rather than wall-clock ordering.

**Timestamp-based (Last Write Wins / LWW).** The most recently updated document wins, based on CAS timestamps. If timestamps are equal, the comparison falls through to sequence number, then TTL, then flags. This depends on clock agreement across clusters, so run NTP and keep skew tight.

Source: [XDCR Conflict Resolution](https://docs.couchbase.com/server/current/learn/clusters-and-availability/xdcr-conflict-resolution.html)

## The policy is fixed at bucket creation

- The policy is a **bucket** property, chosen when the bucket is created, and it **cannot subsequently be changed**.
- If you do not choose, **sequence number-based** is set.
- **XDCR replications cannot be created between buckets with different conflict resolution policies.** Source and target must match.

The practical consequence: switching an existing deployment from sequence-number to timestamp resolution means creating new buckets with the desired policy and moving the data, not flipping a setting. Plan it before the bucket exists.

## Cross cluster versioning and the Hybrid Logical Vector

`enableCrossClusterVersioning` (ECCV) is a bucket property available from **Couchbase Server 7.6.6**, disabled by default. When it is on, XDCR stores extra metadata — the **Hybrid Logical Vector (HLV)**, a set of Hybrid Logical Clock information — on each replicated document, in a system-created extended attribute named **`_vv`**.

Rules you must state plainly to anyone considering it:

- **It cannot be disabled once set to `true`.** Neither can HLV. Do not enable it casually.
- **It cannot be set at bucket creation.** Enable it afterwards via the REST API or the UI.
- If you enable it on one bucket in a replication topology, you must enable it on **all** of them. Buckets on Server versions earlier than 7.6.6 lack the property entirely and therefore cannot participate in a topology that contains ECCV-enabled buckets.
- **XDCR does not validate consistency of the property across buckets.** Verify manually before creating or modifying replications.
- Size cost: **109 + 40N bytes per document**, where N is the number of buckets mutating the document in the topology. Constant while the topology is constant; it accumulates when the topology changes or a copy travels through additional clusters.
- Pruning is controlled by the bucket property **`versionPruningWindowHrs`**, default **720 hours (30 days)**, which must be set to the **same value on all buckets** in the topology.
- **Removing the metadata** requires backing up and restoring into a bucket where ECCV is `false`, using `cbbackupmgr restore --disable-hlv` (8.0+) to strip the xattr. Restoring into an ECCV-disabled bucket without that flag is explicitly documented as not sufficient.
- When ECCV is enabled, HLV metadata feeds into conflict resolution for **both** the sequence-number and timestamp policies.
- **XDCR optimistic replication only applies when ECCV is disabled**, so enabling ECCV changes the throughput profile of small-document replication.

ECCV is a prerequisite for exactly two documented features: **XDCR Active-Active with Sync Gateway**, and **XDCR Conflict Logging**.

Source: [XDCR enableCrossClusterVersioning](https://docs.couchbase.com/server/current/learn/clusters-and-availability/xdcr-enable-crossclusterversioning.html)

## XDCR Conflict Logging (8.0+)

Introduced in **Couchbase Server 8.0**. XDCR detects conflicts arising from independent modifications on different clusters during active-active replication and writes a record of each one into a **conflict log collection** you nominate.

**Prerequisites**

- `enableCrossClusterVersioning` set to `true` on **all** buckets in the replication topology. Only documents mutated **after** ECCV is enabled on both source and target are considered for conflict logging.
- Conflict logging must be enabled on **every leg** of the topology, because conflicts are race conditions and can be detected on either side. A bidirectional pair is two legs; a three-cluster ring with bidirectional links is six.

**Configuration** — the replication setting is `conflictLogging`, a JSON object with:

- `disabled` — boolean
- `bucket` — the bucket holding the conflict log collection
- `collection` — in `[scope].[collection]` form
- `loggingRules` — optional, for per-scope and per-collection overrides, so different parts of the replication can log to different conflict collections

You must specify at least one conflict log collection, which becomes the default. With no `loggingRules`, all detected conflicts go to that default collection. It may be any regular collection in the cluster, including one inside the bucket being replicated.

**What gets written** — each conflict event produces **three documents** in the conflict log collection:

| Document | ID pattern | Content |
|---|---|---|
| Conflict Record Document (CRD) | `crd_<unix_timestamp>_<SHA>` | The conflict event message: document ID, ISO 8601 timestamp, replication ID, and source/target details including CAS, cluster UUID, bucket UUID, revision sequence number, and xattrs including version vectors |
| Source document copy | `src_<unix_timestamp>_<SHA>` | The conflicting document as it stood on the source |
| Target document copy | `tgt_<unix_timestamp>_<SHA>` | The conflicting document as it stood on the target |

These three documents are **not replicated** to other clusters — a system xattr `_xdcr_conflict` keeps them out of replication.

**Behavioural limits you must not gloss over**

- **Conflict logging does not change conflict resolution.** The same version wins as before; you simply get a record of the one that did not.
- Logging is **best-effort: not all conflicts may be logged.** If conflicts surge, XDCR deliberately stops logging to protect replication performance. Do not treat the conflict collection as a complete audit trail.
- **You own the conflict records.** XDCR creates them and does not clean them up. Monitor disk usage on the conflict log collection and delete records once they are no longer needed.
- Tunables prefixed `cLog` exist (worker count default 20, queue capacity 6000, timeouts, hibernation thresholds). The documentation states you must not adjust them unless Couchbase Support advises it. Do not recommend tuning them.
- Before enabling, check that Eventing functions deployed in replicated buckets are not themselves generating excessive conflicts.

Sources: [XDCR Conflict Logging](https://docs.couchbase.com/server/current/learn/clusters-and-availability/xdcr-conflict-logging-feature.html), [What's New in 8.0](https://docs.couchbase.com/server/current/introduction/whats-new.html)

## There is no custom conflict resolution function

Couchbase Server 8.0's XDCR feature set is Conflict Logging, incoming-replication identification, the bundled `xdcrDiffer` utility, and the generic services log level. **There is no JavaScript conflict resolution function, and no `conflictResolutionFunction` replication setting.** The documented policies remain sequence number and timestamp.

If a requirement calls for business-logic merges — "keep the higher bid", "union the two sets" — the supported shape is: pick a resolution policy, enable Conflict Logging, and build an application-side reconciliation process that reads the conflict collection and applies merge logic itself. Say that plainly rather than implying a built-in merge hook exists.

## Minimising conflicts

**Strategy 1 — Key partitioning.** Give each region ownership of a key prefix, so the key spaces do not overlap and conflicts cannot occur. EU writes `eu::user::<id>`, US writes `us::user::<id>`. This is the only strategy that eliminates conflicts rather than managing them.

**Strategy 2 — Collection partitioning.** Replicate each collection in one direction only, even inside an otherwise active-active pair, using explicit collection mapping. The EU cluster owns `eu-orders`; the US cluster owns `us-orders`. Cross-region access goes through application routing, not competing writes.

**Strategy 3 — Design writes that survive resolution.** A field like `event_count: 5` is wrong under any winner, so do not model it that way. Prefer commutative shapes: sets rather than counters, append-only documents rather than in-place edits. Note that Couchbase's sub-document counter operation is atomic within one cluster but is not coordinated across clusters, so it does not solve the cross-cluster case.

**Strategy 4 — Read from the local cluster.** Clients reading only their local cluster's replicated data see eventual consistency but not read-your-own-writes violations for their own writes. See `couchbase-app-integration` for the application-side patterns.

**Strategy 5 — Instrument.** Watch `docs_failed_cr_source` for how often the local side loses resolution, and on 8.0+ use the conflict log collection to see *what* is being lost, not just how much.
