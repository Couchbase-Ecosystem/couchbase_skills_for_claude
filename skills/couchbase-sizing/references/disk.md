# Disk and storage

Memory gets the headlines, but disk sizing matters too — and it's where many sizing exercises trip up because the math is non-obvious. Couchbase writes append-only, so the on-disk footprint exceeds the logical data size until compaction reclaims the space.

> **Documented values are cited; heuristics are labelled *(estimate)*.** Disk IOPS in particular has no documented per-workload table — the figures here are starting points for a load test, not specifications.

## Contents

- [What lives on disk](#what-lives-on-disk)
- [The documented storage equation](#the-documented-storage-equation)
- [Compaction explained](#compaction-explained)
- [Storage type: SSD vs HDD vs cloud volumes](#storage-type-ssd-vs-hdd-vs-cloud-volumes)
- [Storage engines: Couchstore and Magma](#storage-engines-couchstore-and-magma)
- [Index storage](#index-storage)
- [Search Service storage](#search-service-storage)
- [Analytics storage](#analytics-storage)
- [Logs and system](#logs-and-system)
- [Backup storage](#backup-storage)
- [Disk IOPS](#disk-iops)
- [Growth strategies](#growth-strategies)
- [Common mistakes](#common-mistakes)
- [Quick decision tree](#quick-decision-tree)

## What lives on disk

Per node:

1. **Active data** — the partition of documents this node is responsible for
2. **Replica data** — copies of data from other nodes
3. **Compaction overhead** — temporary space during compaction (can briefly equal the bucket size)
4. **GSI / Search / vector index files** — if those services are on this node
5. **Append-only files** for KV (compacted periodically)
6. **System / logs / configs** — small but non-zero

## The documented storage equation

Couchbase publishes an append-only multiplier per storage engine ([Sizing Guidelines](https://docs.couchbase.com/server/current/install/sizing-general.html)). **Use these rather than a guessed compaction factor:**

| Storage engine | Append-only multiplier on the compressed dataset |
|---|---|
| Couchstore | **3×** |
| Magma | **2.2×** |

```
disk_for_data = compressed_dataset_size × append_only_multiplier × (1 + replica_count) × growth_factor
              / data_node_count
```

Where:
- `append_only_multiplier` is **3** (Couchstore) or **2.2** (Magma) — documented
- `growth_factor` is your projected growth over the planning horizon *(your number, from the customer's growth rate)*

Tombstones (deleted-document markers) are accounted for **separately** — the sizing guidelines give their own formula for deleted documents. Don't fold them into the multiplier.

### Worked example

Inputs:
- 100M documents, 1 KB average (compressed size — measure it; JSON compresses well)
- Replica count: 1
- 5 data nodes
- Magma storage engine (multiplier 2.2)
- 18 months projected growth: 3× today

```
dataset_today     = 100M × 1 KB                    = 100 GB compressed
with_replicas     = 100 GB × 2 copies              = 200 GB
at_growth         = 200 GB × 3                     = 600 GB
with_append_only  = 600 GB × 2.2 (Magma)           = 1.32 TB
per_node          = 1.32 TB / 5                    ≈ 264 GB
```

On Couchstore the same workload is `600 GB × 3 = 1.8 TB`, or ~360 GB per node — the engine choice is a ~36% difference in disk before anything else.

Plus index storage, plus tombstones, plus logs, plus OS: provision comfortably above the data figure.

If the budget allows, round up — running out of disk is operationally painful, and the cost of larger SSDs is small.

## Compaction explained

Couchbase uses append-only writes. When a document is updated, the new version is appended; the old version stays until compaction removes it.

Compaction:
- Runs in the background
- Triggered when fragmentation exceeds a configured threshold
- Rewrites the data file to remove old versions
- Consumes additional disk during the rewrite

The documented append-only multipliers (3× / 2.2×) already encode the steady-state cost of this behaviour — that is what they are for. If compaction can't keep up under a very write-heavy workload, fragmentation grows beyond it and you need more headroom than the multiplier gives.

Auto-compaction settings are cluster- and bucket-level: a lower fragmentation threshold means tighter disk use and more compaction CPU; a higher threshold, the reverse. Couchbase Server 8.0 adds configurable **hole-punching granularity** for Plasma-based standard indexes, giving more flexible disk reclamation on the Index service.

## Storage type: SSD vs HDD vs cloud volumes

- **NVMe SSD** — required for production. Couchbase is I/O-intensive; spinning disk is unusable
- **SATA SSD** — OK for non-latency-critical workloads
- **HDD** — only acceptable for backup repositories, never for active data
- **Cloud block storage** (AWS gp3/io2, GCP PD-SSD, Azure Premium SSD / Ultra disk) — works, but provisioned IOPS matters more than capacity for write-heavy workloads
- **Local instance storage** (NVMe attached to the VM) — fastest but ephemeral; only use if your replication strategy can rebuild a lost node fast

For Capella, storage type and IOPS are configured per **service group**: AWS offers gp3 and io2 with IOPS configurable above the default; GCP offers PD-SSD with IOPS derived from capacity (documented as 30 read and 30 write IOPS per GB); Azure offers Premium SSD and Ultra disk with provider-determined IOPS ranges.

## Storage engines: Couchstore and Magma

Couchbase has two storage engines ([Storage Engines](https://docs.couchbase.com/server/current/learn/buckets-memory-and-storage/storage-engines.html)).

| | Couchstore | Magma |
|---|---|---|
| Edition | Enterprise and Community — **the only engine in Community Edition** | **Enterprise Edition only** |
| Status in 8.0 | Still supported | **Recommended for most use cases** |
| Documented memory-to-data floor | 10% of dataset | 1% of dataset |
| Append-only disk multiplier | 3× | 2.2× |
| Minimum bucket RAM quota | 100 MiB | 100 MiB at 128 vBuckets; 1 GiB at 1024 vBuckets |
| vBucket options | not configurable here | 128 or 1024 |

**Magma is not new in 8.0.** What changed in 8.0 is that the **128-vBucket configuration became the default for new buckets in Enterprise Edition**, which is what dropped Magma's minimum bucket quota from 1 GiB to 100 MiB and made it viable for small buckets as well as large ones. 7.x clusters can and do run Magma — gate advice on edition, not just version.

Magma is the better choice when the dataset per node is large relative to RAM (its 1% memory-to-data floor against Couchstore's 10% is the headline difference), and it is the documented pairing for **full ejection**.

Set the storage engine when creating the bucket. Changing it afterwards requires a rebuild.

## Index storage

GSI indexes live on disk under **standard (disk-optimized) index storage**, which is the default. Couchbase documents that with standard storage "the total size of the index can be much bigger than the amount of memory available in each index node," because it uses both memory and disk.

The alternative, **memory-optimized index storage**, keeps all index data in memory using a lock-free skiplist and is **Enterprise Edition only**. It requires enough Index service memory quota to hold every resident index, and performance degrades as usage approaches the quota (index updates pause at 95% of quota). Standard storage is backed by Plasma in Enterprise Edition and ForestDB in Community Edition.

Couchbase does not publish a general GSI-size-per-document formula, so **don't quote one.** Size index storage empirically: build the index on a representative sample and extrapolate. Vector indexes are a different and much larger problem — see `indexes.md`.

Plan index storage as a separate budget. If you're running the Index service on the same nodes as Data, allocate disk for both.

## Search Service storage

Couchbase does not publish a general Search index size ratio ("FTS" is the older
name for the Search Service), and the real figure depends heavily on the analyzer, which fields are stored, and whether vectors are involved. **Measure it**: build the index on a representative sample of the corpus and extrapolate from the observed size.

Vector indexes (8.0+) are much larger — `indexes.md`.

Same pattern: allocate an explicit disk budget for the Search Service if it's on this node.

## Analytics storage

Analytics maintains its own copies of the source data in an analytics-optimized form, so its storage requirement scales with the source dataset it ingests. Couchbase does not publish a general multiplier for this; size it against a representative ingest rather than a rule of thumb.

Note there are two distinct products in this space: the **Analytics Service** that runs as a service within a Couchbase Server cluster, and **Capella Analytics** / **Couchbase Enterprise Analytics**, which are separate analytics products with their own sizing model and documentation. (The name "Capella Columnar" is retired — it is Capella Analytics now.) Establish which one the user means before sizing anything.

## Logs and system

- Couchbase logs grow with activity. Default rotation keeps recent ones; adjust rotation settings if growth is a problem
- Audit logs (when enabled) can grow fast — plan separate disk if audit is high-volume
- Don't put data and logs on the same disk; log writes can compete with data I/O

## Backup storage

Backups go to a separate location — typically:
- Local backup repository on a backup node's disk
- Network-attached storage (NFS)
- Object storage (S3, GCS, Azure Blob)

Backup storage ≈ total data × the number of retained copies, adjusted for how much incrementals actually change. The multiplier is entirely a function of *your* retention policy and change rate — compute it from those rather than adopting a generic figure.

Couchbase Server 8.0 adds **configurable retention periods and automatic pruning of expired backups** to the Backup Service, plus override protection for incremental backup deletion — which makes the retention policy something the cluster enforces rather than something you script.

This is on top of the cluster's own storage.

## Disk IOPS

IOPS matters as much as capacity for write-heavy workloads. **Couchbase does not publish an IOPS-per-workload table**, and the correct value depends on document size, write rate, compaction settings, storage engine and index count.

The figures below are **starting points for a load test** *(estimate)*, not specifications — present them that way, and replace them with the IOPS your own load test drives:

| Workload type | Starting point, IOPS per data node *(estimate)* |
|---|---|
| Read-heavy | low thousands |
| Balanced | mid thousands |
| Write-heavy | high thousands and up |
| Vector-index-heavy | high thousands and up — index maintenance is I/O-expensive |

For cloud volumes, provision IOPS explicitly. Default volumes often have IOPS limits that silently cap write throughput — the symptom is a throughput ceiling with no error, which is why it needs to be load-tested rather than reasoned about.

## Growth strategies

Disk has friendlier scaling than RAM in most ways:

- **Grow vertically:** swap volumes to larger ones, or extend cloud volumes online. No data movement needed
- **Grow horizontally:** adding a node spreads the data wider, reducing per-node disk pressure

In Capella, disk configuration is per service group, and storage can be expanded (AWS and GCP allow raising IOPS above the default; Azure requires selecting a different disk type to increase storage) without re-sizing compute.

## Common mistakes

- **Sizing for just the data, ignoring the append-only multiplier** — disk fills up sooner than expected. Use 3× (Couchstore) or 2.2× (Magma)
- **Sizing from uncompressed document size** — the documented multiplier applies to the *compressed* dataset; JSON compresses well, so measure compressed size
- **Forgetting tombstones** — deleted documents leave markers that occupy space and are accounted for separately from the multiplier
- **Putting Couchbase data and logs on the same volume** — log writes interfere with data I/O
- **Using HDD for active data** — unusable performance
- **Provisioning minimum IOPS in cloud** — write throughput hits a wall, no clear error
- **Forgetting backup storage** — typically several times the cluster's own storage
- **Sizing for today, not 18 months from now** — disk migration is annoying enough that planning ahead pays off

## Quick decision tree

- **Calculating from scratch?** `compressed_dataset × append_only_multiplier × (1 + replicas) × growth / nodes`, where the multiplier is **3** for Couchstore and **2.2** for Magma
- **Large dataset per node?** Magma — 1% memory-to-data floor vs Couchstore's 10%, and a lower disk multiplier. **Enterprise Edition only**
- **Community Edition?** Couchstore is your only engine; size at the 3× multiplier and the 10% memory floor
- **High write rate?** Load-test to find the IOPS you actually need; don't provision from a table
- **Mixed services on one node?** Add up the storage for each service's needs
- **Backup planning?** Derive from *your* retention policy and change rate, not a generic multiplier
- **Production?** Always NVMe SSD or top-tier cloud SSD; never HDD for active data
