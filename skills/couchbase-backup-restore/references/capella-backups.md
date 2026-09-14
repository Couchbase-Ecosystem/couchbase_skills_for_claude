# Capella managed backups

Capella has **two distinct backup mechanisms** that people routinely confuse. Establish which one the conversation is about before answering anything.

## Contents

- [Bucket backups vs Cloud Snapshot cluster backups](#bucket-backups-vs-cloud-snapshot-cluster-backups)
- [Bucket backups](#bucket-backups)
- [Cloud Snapshot cluster backups](#cloud-snapshot-cluster-backups)
- [What a Capella restore does NOT bring back](#what-a-capella-restore-does-not-bring-back)
- [Cross-cluster restore and minimum versions](#cross-cluster-restore-and-minimum-versions)
- [Downloading a bucket backup](#downloading-a-bucket-backup)
- [Encryption](#encryption)
- [Before a planned maintenance event](#before-a-planned-maintenance-event)

## Bucket backups vs Cloud Snapshot cluster backups

| | Bucket backup | Cloud Snapshot cluster backup |
|---|---|---|
| Scope | One bucket's data | The cluster's entire storage, all buckets |
| Types | Full + Incremental | Each backup is a standalone full backup from Capella's point of view |
| Underlying mechanism | Capella's own backup utility, run in a dedicated compute instance | The cloud provider's disk snapshot service (Amazon EBS Snapshots, Google Cloud Standard Disk Snapshots, Azure Disk Backup) |
| Downloadable | Yes (up to 5 TB) | No |
| Restores indexes | GSI definitions are restored as `Created`, not built | Yes — snapshot restore includes indexes |
| Memory Only (ephemeral) bucket data | Yes | **No** — use a bucket backup |
| Typical use | Granular restore, data migration, restore into a different cluster | Fast whole-cluster disaster recovery, typically within minutes |
| Stored | Managed by Capella | At project level in the organization; survives cluster deletion |

Sources: [Back Up and Restore Bucket Data](https://docs.couchbase.com/cloud/clusters/backup-restore.html), [Back Up and Restore An Entire Cluster](https://docs.couchbase.com/cloud/clusters/cloud-snapshots.html)

## Bucket backups

Configured per bucket, at bucket creation or later.

- **Weekly schedule** is the current model: a weekly full backup, followed by incrementals at an hourly interval you choose. You can also choose not to back a bucket up at all.
- **Daily schedule is deprecated.** Since January 2023, new Capella users and new clusters cannot set a daily bucket backup schedule. Existing users with an existing daily schedule on a pre-existing cluster keep it indefinitely.
- **On-demand backups** are available at any time and are retained for 30 days.
- **Retention** is set by the bucket's Retention Time, from 30 days to five years. It applies only to future backups — changing it does not affect backups already taken.
- **Cost Optimized Retention** trades RPO for cost: every backup cycle is kept for four weeks, but only the **last backup cycle of each monthly period** is kept for the full retention time. So you can restore from any backup in the last four weeks, and beyond that only from the monthly restore point.
- A **cycle** is one weekly full plus the incrementals that follow it. Cycles matter because downloads operate on completed cycles.
- The backup utility runs in a **separate compute instance** that Capella spins up and decommissions per job, which limits the impact on cluster performance.
- Backups continue to expire while a cluster is turned off, and scheduled backups do not run while it is off. If you plan to turn a cluster off past a backup's expiry, download what you need first.
- If a cluster is scheduled to turn off while a backup or restore is pending or active, Capella waits for it to finish. An on-demand turn-off during a backup or restore returns an error instead.

### Bucket restore options

- Restore in place, or to a **different cluster in the same organization**.
- The destination bucket must **already exist** with the **same name and the same conflict resolution method** as the bucket in the backup. Capella resolves conflicts during restore using the buckets' configured conflict resolution method; an option is available to overwrite newer document versions with earlier ones from the backup.
- **Filter Keys** and **Filter Values** accept RE2 regular expressions, so you can restore a subset of the dataset.
- Restored GSI indexes are distributed round-robin across the nodes running the Index Service and are left in the `Created` state, **not built** — deliberately, so you can move them before building. Build them from the Indexes page (or with `BUILD INDEX`) after the restore.

## Cloud Snapshot cluster backups

- Each backup is independently restorable and deletable, even though the provider's underlying snapshots are incremental. Deleting one leaves the data other backups still need.
- **Azure caveat:** Azure caps incremental snapshots at 500. After 500, it starts taking full backups, and costs rise sharply.
- **Cross-region copies:** on **AWS and Azure clusters running Couchbase Server 7.6.6 and later**, a cluster backup can be copied to two additional regions of your choice, and any copy can be used for a restore. GCP-hosted clusters cannot replicate cluster backups to another region. If you use a customer-managed encryption key on Azure, you cannot use cross-region copies.
- Restore targets: the same cluster, another compatible cluster, or a **new cluster with an identical configuration**.

## What a Capella restore does NOT bring back

This is the part customers get wrong. For a **Cloud Snapshot cluster backup restore**:

- **All existing data on the destination cluster is destroyed first.** The cluster is unusable during the restore.
- **All cluster access credentials are deleted.**
- **All allowed IP addresses (CIDR allow-list entries) are deleted.**

  Before restoring, use Management API v4 to list the cluster access credentials and the allowed IP addresses so you can recreate them afterwards.
- **Node configuration is reverted to the backup's node count.** If you scaled the cluster between backup and restore, Capella scales it back to what the backup recorded.
- **Memory Only bucket data is not captured**, so it is not restored.

For a **bucket backup**:

- A bucket backup is **not a point-in-time snapshot**. Data is per-item consistent, but consistency *across* items is not guaranteed. The utility aims for a strong consistency window — usually a few seconds — but under resource pressure or network trouble it cannot be guaranteed. The state of one item does not imply the state of another.
- **Cluster settings are not included** — nodes, replication, networking, cluster access.
- Restored indexes are created but **not built**.

Couchbase App Services backup and restore behaviour is not covered by these pages; treat App Services configuration and data as separately managed and confirm with Couchbase before telling a customer a Capella backup covers it.

## Cross-cluster restore and minimum versions

- **Cluster backups:** you can only restore a backup to a *different* cluster if **both clusters are running Couchbase Server 7.6.6 or later**. If either is on an earlier version, cross-cluster restore is unavailable. Concretely: a backup taken on a 7.6.5 cluster cannot be restored to a 7.6.6 cluster until the 7.6.5 cluster is upgraded.
- Backups taken while a cluster was on 7.6.5 can still be restored **to that same cluster** after it is upgraded — but doing so temporarily returns the cluster to 7.6.5, and you re-run the upgrade afterwards.
- **Bucket backups:** can only be restored to a cluster running the **same major version or later** as the cluster that produced them.
- If the cluster backup has cross-region copies, Capella prefers the copy in the destination's region when creating a new cluster, to reduce data transfer.

Source: [Back Up and Restore An Entire Cluster](https://docs.couchbase.com/cloud/clusters/cloud-snapshots.html), [Restore a Bucket Backup](https://docs.couchbase.com/cloud/clusters/manage-restore.html)

## Downloading a bucket backup

Cluster backups cannot be downloaded. Bucket backups can — on-demand backups as soon as they complete, scheduled backups once the cycle is complete.

- Request the download in Capella; you are notified by email when the file is ready. You then have **12 hours** to retrieve the download URL, and must **start the download within 1 hour** of copying it.
- Limit: a bucket backup over **5 TB** cannot be downloaded.
- Supported on AWS, GCP, and Microsoft Azure.
- The file is a zip named `{cluster name}-{bucket-name}-{scheduled|on-demand}-{date or date range}.zip`. Unzipped, it is a `cbbackupmgr` archive whose archive and repository names are the same UUID, so you inspect it with `cbbackupmgr info --archive <path>/<uuid> --repo <uuid>`.
- Capella provides a SHA-256 checksum in the UI for verification.
- Capella stores the prepared download file for roughly 24 hours and charges for that storage; using the URL incurs data transfer charges.

When running `cbbackupmgr` directly against a Capella cluster with cluster access credentials, several `--disable-*` options are required (see `--capella` in `restore.md`). Those restrictions do not apply when you operate on a downloaded archive against a self-managed cluster.

## Encryption

If a cluster uses customer-managed encryption keys (CMEK) for its storage, its **cluster backups** use that CMEK. Otherwise Capella's standard encryption applies. You cannot opt a cluster backup into CMEK if the cluster itself is not CMEK-encrypted, and **bucket backups do not support CMEK**.

Do not delete a KMS Key ID while cluster backups using it are still live — the backup becomes unusable, and recovering it requires Couchbase Capella Support. Key IDs must be enabled and available to restore an encrypted backup.

## Before a planned maintenance event

Take a manual backup before cluster upgrades, significant data model changes, and bulk deletes or migrations. Wait for it to complete before proceeding. For a whole-cluster safety net that restores quickly, prefer an on-demand **cluster backup**; for something you can inspect, filter, or restore elsewhere, take an on-demand **bucket backup**.
