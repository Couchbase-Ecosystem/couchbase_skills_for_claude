---
name: couchbase-backup-restore
description: "Plan and execute Couchbase backup and restore operations. Use whenever the user asks about backup, restore, cbbackupmgr, the Backup Service, backup repository, backup archive, full backup, incremental backup, backup merge, backup pruning and retention, backup verification, encrypted backups, Capella managed backups (bucket backups and Cloud Snapshot cluster backups), backup to S3 or other object stores, restoring a bucket, restoring a scope or collection, or 'how do I back up / restore Couchbase.' Distinct from couchbase-migration-execution (one-time data migration to a new cluster). Use proactively for DR planning, RPO/RTO requirements, backup verification workflows, and pre-upgrade snapshots."
license: Apache-2.0
---

# Couchbase Backup & Restore

A skill for *planning and executing* Couchbase backup and restore — self-managed (`cbbackupmgr` and the Backup Service) and Capella-managed.

Distinct from `couchbase-migration-execution` — one-time data migration, not recurring backup.

## When this skill applies

- "How do I back up Couchbase?" / "What's cbbackupmgr?"
- "How do I set up a backup schedule?"
- "Full vs incremental backup — what's the difference?"
- "How do I restore from backup? Just one bucket? Just one collection?"
- "How do I back up to S3 / Azure Blob / Google Cloud Storage?"
- "How do I encrypt backups?"
- "How do I verify my backups are actually working?"
- "How does Capella handle backups, and what does a restore actually bring back?"

## Pick the right reference

| Question | Read |
|---|---|
| "cbbackupmgr commands — config, backup, restore, info, merge, examine, compact, remove" | `references/cbbackupmgr.md` |
| "Backup strategy — full vs incremental, merge, retention, object storage, encryption" | `references/strategy.md` |
| "How to restore — full cluster, one bucket, one collection, remapping, users, Capella targets" | `references/restore.md` |
| "Capella managed backups — bucket backups vs Cloud Snapshot cluster backups, and what restore does NOT bring back" | `references/capella-backups.md` |

## Edition and version gating (read before recommending anything)

- **`cbbackupmgr`** ships with both Enterprise Edition and Community Edition. From 7.0, CE has it **without** `merge`, cloud (object store) backup, or collection-level restore. `examine` is also Enterprise-only. ([docs](https://docs.couchbase.com/server/current/manage/manage-backup-and-restore/manage-backup-and-restore.html))
- **The Backup Service** (the in-cluster, schedulable service configured from the Backup tab in the Web Console, CLI, and REST API) is **Enterprise Edition only**.
- **Scope/collection-level include/exclude** is an Enterprise Edition feature; in CE, backup and restore operate at bucket granularity only.
- **Users and groups** are backed up only when you opt in (`--enable-users`), and backup/restore of users requires **Couchbase Server 7.6+** — the flag is ignored on earlier versions.
- **The `_system` scope** (internal Couchbase service data) is backed up on clusters running **7.6+**.
- **Object-store archives** require Enterprise Edition (native cloud integration, introduced in 6.6.0). Azure Blob (`az://`) requires **7.1.2+**.
- **Retention periods on repositories and scheduled pruning of old backups** in the Backup Service are **8.0+**. ([What's New in 8.0](https://docs.couchbase.com/server/current/introduction/whats-new.html))
- **`cbbackupmgr restore --disable-hlv`**, used to strip cross-cluster-versioning metadata, is **8.0+**.

## Three core principles

**Principle 1 — An untested backup is not a backup.**
Run a restore drill regularly — quarterly at minimum, more often for production data. Use `cbbackupmgr info` to inspect what a repository and its backups actually contain without a restore. A restore into a staging cluster is the only way to know your backups are complete and your procedure works.

Note the tool boundaries: `info` reports on the archive, repositories and backups. `examine` (Enterprise Edition) searches **by a single document key** and prints an event timeline for that key — it is not a bulk content lister and it is not an integrity checker.

**Principle 2 — Incremental backups depend on the chain before them.**
All `cbbackupmgr` backups into an existing repository are incremental by default; the first one is implicitly full, and `--full-backup` forces another. To restore to a given backup you need the preceding full backup plus every incremental up to it. Keep multiple full generations, and use `merge` (Enterprise Edition) to collapse a full plus its incrementals into a new self-contained full before deleting the originals.

**Principle 3 — Backup is not DR.**
Backup protects against data corruption, accidental deletion, and ransomware. It does not protect against site loss at a low RPO — that is what XDCR is for. Most production deployments need both: XDCR for fast failover, backup for recovery from logical errors that XDCR would faithfully replicate.

## Operating the tooling

- **Self-managed, ad hoc or scripted:** `cbbackupmgr` from the command line. See `references/cbbackupmgr.md`.
- **Self-managed, scheduled:** the Backup Service, via the Backup tab in Couchbase Web Console, `couchbase-cli`, or the Backup Service REST API. It builds on `cbbackupmgr` technology but adds plans, schedules, periodic merges, retention and pruning.
- **Capella:** bucket backups and Cloud Snapshot cluster backups, from the Capella UI or Management API v4. See `references/capella-backups.md`.
- **MCP:** the official Couchbase MCP server (`couchbase/mcp-server-couchbase`, https://mcp-server.couchbase.com/) is a **data-plane** server and is **read-only by default** (`CB_MCP_READ_ONLY_MODE`). It does **not** expose backup or restore operations. Drive backup and restore through the CLI, REST API, or UI, and use MCP only to inspect data before and after a restore.

## RBAC

For `cbbackupmgr`, the **Full Admin** or **Data Backup & Restore** role must be assigned. For the Backup Service, **Full Admin** must be assigned. Restoring users additionally requires permission to create those same users — a Read-Only Admin cannot restore users. ([docs](https://docs.couchbase.com/server/current/manage/manage-backup-and-restore/manage-backup-and-restore.html))

Note that the `cbbackupmgr` reference page states more narrowly that only Full Administrators can use the tool; if you are designing a least-privilege service account, test the Data Backup & Restore role against your exact command set before relying on it.

## RPO/RTO guidance

RPO is set by how often you take an incremental; RTO is dominated by dataset size, restore parallelism, and index rebuild time. Measure both on your own data — the figures below are shapes, not benchmarks.

| Approach | RPO driver | RTO driver | Notes |
|---|---|---|---|
| Scheduled incrementals, hourly | Backup interval | Restore + index build | Common baseline for self-managed |
| Scheduled incrementals, sub-hourly | Backup interval | Restore + index build | More storage and more source I/O |
| XDCR + backup | Replication lag (XDCR); backup interval (backup) | Failover (XDCR); restore (backup) | The usual production combination |
| Capella bucket backups | Chosen hourly incremental interval | Restore duration | Weekly full plus incrementals |
| Capella Cloud Snapshot cluster backups | Backup interval | Snapshot restore duration | Restores indexes too; destroys existing cluster data first |

## Related skills

- `couchbase-xdcr` — replication for low-RPO/low-RTO site failover (complements backup, not a replacement)
- `couchbase-migration-execution` — one-time migration, which uses similar tooling
- `couchbase-capella` — Capella cluster administration
- `couchbase-admin-mcp` — running and restoring backups through the admin MCP server's backup tool family
- `couchbase-kubernetes` — scheduling these backups as `CouchbaseBackup` resources under the Operator
- `couchbase-security-hardening` — key management and encryption at rest behind encrypted backup archives
- `couchbase-upgrade` — the upgrade plan a pre-upgrade backup is taken for
