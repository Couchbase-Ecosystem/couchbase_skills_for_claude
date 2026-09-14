---
name: couchbase-magma
description: "Understand, choose, and tune the Magma storage engine in Couchbase Server. Use whenever the user asks about Magma, the Couchbase storage backend, Couchstore vs Magma, 128 vBuckets vs 1024 vBuckets, Magma memory-to-data ratio, minimum bucket memory quota, Magma compaction and fragmentation settings, storage engine selection for a new bucket, the storageBackend or numVBuckets bucket properties, migrating a bucket's storage backend, or 'which storage engine should I use.' Also covers what changed when Magma with 128 vBuckets became the default for new Couchbase buckets in Enterprise Edition 8.0. Distinct from couchbase-sizing, which has a brief Magma section in disk.md; this skill covers engine behavior, tradeoffs, and tuning in depth. Use proactively when the user is creating buckets or investigating storage-related performance."
license: Apache-2.0
---

# Couchbase Magma Storage Engine

Understanding, choosing, and tuning Magma — Couchbase's storage backend designed for large datasets held with a low memory-to-data ratio.

**Edition and version gating:** Magma is **Enterprise Edition only**. It was introduced in Couchbase Server 7.1. The 128 vBucket configuration and the "Magma by default" behavior are **8.0+ EE only**. Community Edition uses Couchstore with 1024 vBuckets on every version.

## When this skill applies

- "Should I use Magma or Couchstore for my bucket?"
- "What changed with Magma being the default in 8.0?"
- "128 vBuckets or 1024?"
- "How much memory does a Magma bucket need?"
- "Can I move an existing bucket from Couchstore to Magma?"
- "How does Magma compaction differ?"
- "My write performance changed after upgrading"

## Magma vs Couchstore at a glance

| | Couchstore | Magma |
|---|---|---|
| **Editions** | Community and Enterprise | Enterprise only |
| **Available from** | All supported versions | 7.1+ (128 vBucket config: 8.0+) |
| **vBucket count** | 1024 | 128 or 1024 |
| **Minimum bucket RAM quota** | 100 MiB per node | 100 MiB per node (128 vBuckets) / 1 GiB per node (1024 vBuckets) |
| **Memory-to-data ratio** | 10% | 1% |
| **Max data per node** | 3 TB | 10 TB (both vBucket configurations) |
| **Best fit** | Working set fits in memory and is under ~20% of the dataset | Working set does not fit in memory, or is more than 20% of the dataset |
| **Compaction** | Threshold-driven, with an optional time window | Threshold-driven fragmentation target; no time-window setting |

Source: https://docs.couchbase.com/server/current/learn/buckets-memory-and-storage/storage-engines.html

## Choosing an engine

The documented decision is about **working-set residency**, not document counts or write rates:

**Choose Couchstore when:**
- "You have a dataset with a working set that fits into available memory and the working set is less than 20% of the total dataset."
- You are on Community Edition (Magma is not available).

**Choose Magma with 128 vBuckets when:**
- "You want to minimize memory use and have a working dataset that does not fit in the available memory or is more than 20% of the total dataset."
- Your dataset is under 100 GiB — at that size the 128 vBucket configuration saves memory versus the 1 GiB minimum of the 1024 vBucket configuration.

**Choose Magma with 1024 vBuckets when:**
- "Your dataset will grow beyond Couchstore's 3 TB limit."
- You need to store and access multiple terabytes using a small amount of memory.
- The dataset is large enough that data imbalance matters — at scale, "the 1024 vBucket configuration is less likely to have data imbalance issues than the 128 vBucket configuration."
- Note the docs' tradeoff in the other direction: Magma with 1024 vBuckets "uses less CPU for operations such as compaction" than the 128 vBucket configuration.

Full ejection pairs well with Magma: the docs recommend full ejection specifically for buckets using Magma with low memory-to-data ratios.

## vBucket count: 128 vs 1024

- **The count is fixed at bucket creation.** "Once created, the number of vBuckets in a bucket does not change." Plan before creating production buckets.
- Couchstore is always 1024 on Linux and Windows. Magma offers 128 or 1024.
- On macOS, every bucket uses 64 vBuckets regardless of storage engine (development only).
- 128 vBuckets lowers the per-bucket memory floor from 1 GiB to 100 MiB. That is the main reason it is the 8.0 default.
- 1024 vBuckets gives finer-grained distribution, which reduces the chance of data imbalance on larger clusters, at a higher memory floor and higher compaction CPU per the note above.

Source: https://docs.couchbase.com/server/current/learn/buckets-memory-and-storage/vbuckets.html

## Memory requirements

- **Couchstore:** minimum 100 MiB per bucket per node; memory-to-data ratio 10%.
- **Magma, 128 vBuckets:** minimum 100 MiB per bucket per node; memory-to-data ratio 1%.
- **Magma, 1024 vBuckets:** minimum 1 GiB per bucket per node; memory-to-data ratio 1%.

The docs' worked example: "a node with 5 TiB data in a Magma bucket must allocate at least 51 GiB of RAM." The 10× difference in required memory-to-data ratio versus Couchstore is Magma's core advantage for large, memory-constrained datasets.

## Setting storage engine and vBucket count

Via the Couchbase Web Console (Create Bucket → Advanced Settings), the REST API (`storageBackend`, `numVBuckets`), the CLI, or MCP:

```python
admin_bucket_create(
    name="my-bucket",
    ram_quota_mb=4096,
    storage_backend="magma",    # "couchstore" or "magma"
    num_vbuckets=128,           # 128 or 1024 (Magma); Couchstore is 1024
    cluster="prod"
)
```

Defaults if you omit these:
- **8.0+ Enterprise Edition:** Magma with 128 vBuckets
- **Pre-8.0, or any Community Edition version:** Couchstore with 1024 vBuckets

Set both explicitly in deployment scripts and IaC rather than relying on the default — the default changed at 8.0 and differs by edition.

## Compaction and fragmentation

**Couchstore** compacts per-vBucket by rewriting the file. It is driven by a fragmentation threshold (percentage and/or size) and can be confined to an allowed time window, with an option to abort when the window closes.

**Magma** is also fragmentation-threshold driven, but the settings differ:
- Magma buckets expose a **Magma Fragmentation Percentage** setting. The Web Console shows 50% for this field; the supported range is 10–100. Verify the effective value on your own cluster rather than assuming.
- **The time-interval setting does not apply to Magma.** Per the docs, the Time Interval section "only appears for buckets using the Couchstore storage engine. It does not appear for Magma buckets." You cannot confine Magma compaction to a maintenance window.
- Practically this means Magma's disk I/O from compaction is spread out rather than appearing as the sawtooth pattern Couchstore compaction produces. Do not read the absence of that pattern as a problem.

Magma may use more disk than Couchstore for the same data, depending on the fragmentation setting. Size disk accordingly.

Sources: https://docs.couchbase.com/server/current/manage/manage-settings/configure-compact-settings.html and https://docs.couchbase.com/operator/current/resource/couchbasebucket.html

## Migrating between storage engines

**8.0+ EE supports backend migration for an existing bucket** — you do not have to create a new bucket and copy data, provided the vBucket count is not changing.

How it works:
1. Change the bucket's storage backend setting. This "does not trigger an immediate conversion of the vBuckets to the new backend. Instead, Couchbase adds override settings to each node."
2. Force the vBuckets to be rewritten. "The two ways to trigger this rewrite are to perform a swap rebalance or a graceful failover followed by a full recovery."

Constraints that matter:
- **Migrating to Magma always produces a 1024 vBucket bucket**, regardless of the original bucket's vBucket count. If you want a 128 vBucket Magma bucket, this path will not get you there.
- **Backend migration does not support migrating between buckets with different numbers of vBuckets.** Use XDCR for that case.
- **It is reversible.** You can go Magma → Couchstore (deactivating history retention first) or Couchstore → Magma by running the process in the other direction.
- Enterprise Edition only, 8.0+.

Source: https://docs.couchbase.com/server/current/manage/manage-buckets/migrate-bucket.html

**Pre-8.0, or when the vBucket count must change**, use a data-copy approach instead:

1. **New bucket + XDCR or cbimport/cbexport**, then cut over. See `couchbase-migration-execution`.
2. **Backup and restore:** `cbbackupmgr` the source bucket, create the target bucket with the storage engine and vBucket count you want, restore into it.

Both require planning for the copy duration on large datasets, and a cutover window.

## Upgrade interaction

Magma is **not usable in mixed mode** during a cluster upgrade — the docs state "Magma should not be switched on until all nodes have been upgraded." Complete the upgrade of every node before changing any bucket to Magma. See `couchbase-upgrade`.

## Related skills

- `couchbase-sizing` — Magma sizing formulas and disk planning
- `couchbase-upgrade` — the 8.0 default change and its impact on bucket creation scripts
- `couchbase-performance-tuning` — storage-related I/O and compaction symptoms
- `couchbase-migration-execution` — moving data between buckets
