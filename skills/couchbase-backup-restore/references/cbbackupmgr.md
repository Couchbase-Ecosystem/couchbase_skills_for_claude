# cbbackupmgr

The CLI for self-managed backup and restore. Runs on any host that can reach both the cluster and the backup archive.

## Contents

- [Edition gating](#edition-gating)
- [Concepts and terminology](#concepts-and-terminology)
- [Subcommands](#subcommands)
- [config — create a backup repository](#config--create-a-backup-repository)
- [backup — run a backup](#backup--run-a-backup)
- [info — inspect the archive](#info--inspect-the-archive)
- [examine — trace a single key](#examine--trace-a-single-key)
- [merge — consolidate backups](#merge--consolidate-backups)
- [compact and remove](#compact-and-remove)
- [Selecting a range with --start and --end](#selecting-a-range-with---start-and---end)
- [Object-store archives](#object-store-archives)
- [Encrypted repositories](#encrypted-repositories)
- [The Backup Service](#the-backup-service)
- [Authentication and RBAC](#authentication-and-rbac)

## Edition gating

`cbbackupmgr` is present in Enterprise Edition and, from 7.0, in Community Edition. Community Edition does **not** have `merge`, object-store (cloud) archives, or collection-level restore, and works at bucket granularity only. `examine` and encrypted repositories are Enterprise Edition. Source: [Manage Backup and Restore](https://docs.couchbase.com/server/current/manage/manage-backup-and-restore/manage-backup-and-restore.html) and [cbbackupmgr](https://docs.couchbase.com/server/current/backup-restore/enterprise-backup-restore.html).

From 7.2, `cbbackupmgr` is distributed in the separately downloaded Server Tools package rather than only with the server install.

## Concepts and terminology

- **Archive** — the top-level directory (or object-store prefix) holding one or more repositories plus client logs. Only one backup client may operate on an archive at a time; concurrent clients can corrupt it.
- **Repository** — a backup configuration plus the backups taken under it. Create one per cluster.
- **Backup** — one run. Every backup is an incremental; the first one in a repository is implicitly full.
- **Collection string** — a dot-separated path `bucket`, `bucket.scope`, or `bucket.scope.collection`, used by `--include-data`, `--exclude-data`, `--map-data`, and `examine --collection-string`.

## Subcommands

`backup`, `restore`, `config`, `info`, `merge`, `compact`, `remove`, `examine`, `collect-logs`.

There is no `list` subcommand in current releases — it was replaced by `info`. If you are reading an older runbook that calls `cbbackupmgr list`, translate it to `cbbackupmgr info`.

## config — create a backup repository

```bash
cbbackupmgr config \
    --archive /backup/couchbase-archive \
    --repo prod-cluster
```

`config` is where you decide **what** the repository backs up. The defaults capture data and metadata; you narrow or widen with flags that are then inherited by every `backup` run in that repository:

- `--include-data <collection_string_list>` / `--exclude-data <collection_string_list>` — mutually exclusive. Scope/collection granularity is Enterprise Edition.
- `--enable-users` — back up users and user groups (including hashed passwords). **Off by default.** Requires Couchbase Server 7.6+; ignored on earlier versions.
- `--disable-data` — metadata only. Useful for transferring settings to a new cluster: you still get bucket configuration, GSI definitions, Search indexes and aliases, views, Eventing functions, Query SQL++ user-defined functions, analytics collections/indexes for local links and synonyms, and (7.6+) scope and collection definitions.
- `--disable-bucket-config`, `--disable-views`, `--disable-gsi-indexes`, `--disable-ft-indexes`, `--disable-ft-alias`, `--disable-analytics`, `--disable-cluster-analytics`, `--disable-eventing`, `--disable-bucket-query`, `--disable-cluster-query` — exclude specific metadata classes.
- `--capella` — omit services Capella does not support, so the repository can be restored into a Capella cluster.
- `--vbucket-filter <list>` — restrict to specific vBuckets.

Index definitions and other service metadata are included **by default**. There is no `--include-indexes` flag; you opt *out* with the `--disable-*` flags above.

`cbbackupmgr` does not back up Query function libraries (user-created JavaScript libraries). Back those up separately.

## backup — run a backup

```bash
# Incremental (the default behaviour in an existing repository)
cbbackupmgr backup \
    --archive /backup/couchbase-archive \
    --repo prod-cluster \
    --cluster couchbase://10.0.0.1 \
    --username <backup-user> \
    --password <pass>

# Force a full backup in the same repository
cbbackupmgr backup \
    --archive /backup/couchbase-archive \
    --repo prod-cluster \
    --cluster couchbase://10.0.0.1 \
    --username <backup-user> \
    --password <pass> \
    --full-backup
```

The first backup into a new repository is always full. `--full-backup` re-streams all data, which costs more time and disk than an incremental.

Useful options:

- `-t, --threads <num>` — concurrent clients. **Defaults to 1.** Do not exceed the CPU count of the backup host.
- `--value-compression <unchanged|uncompressed|compressed>` — how values are stored in the archive.
- `--resume` / `--purge` — if the previous run failed partway, `--resume` continues it and `--purge` discards the partial and restarts from the last successful backup. Mutually exclusive.
- `--consistency-check <window>` — report on cross-item consistency.
- `--skip-last-compaction`, `--no-progress-bar`.

Backups can run during a rebalance; `cbbackupmgr` tracks data as it moves. Both operations are resource-intensive, so expect temporary performance impact. If a node fails mid-backup, `cbbackupmgr` waits 180 seconds for it to return or be failed over, then marks that node's data as failed and finishes the rest as a partial backup.

## info — inspect the archive

```bash
cbbackupmgr info \
    --archive /backup/couchbase-archive \
    --repo prod-cluster \
    --json
```

`info` is the command for "what is in this archive / repository / backup" — backups, sizes, item counts, and what services are covered. `--json` for machine-parseable output. It does not need a running cluster, which makes it the right verification step after every backup run.

## examine — trace a single key

```bash
cbbackupmgr examine \
    --archive /backup/couchbase-archive \
    --repo prod-cluster \
    --collection-string orders.my-scope.active-orders \
    --key "order::abc123" \
    --json
```

Enterprise Edition. `examine` finds one key and produces a timeline of events for it across the backups in range — first appearance, mutations, deletion. It is not a way to list all keys or count documents. Output can include or omit metadata, xattrs, and value (`--no-meta`, `--no-xattrs`, `--no-value`, and the `--hex-*` variants), and can be limited to a backup range with `--start` / `--end`.

Source: [cbbackupmgr examine](https://docs.couchbase.com/server/current/backup-restore/cbbackupmgr-examine.html)

## merge — consolidate backups

```bash
cbbackupmgr merge \
    --archive /backup/couchbase-archive \
    --repo prod-cluster \
    --start oldest \
    --end 2026-05-01T00_00_00.000000000+00_00
```

Enterprise Edition. Merging turns a run of incrementals into a single full backup inside the archive, reclaiming per-backup metadata space and (in the SQLite format) deduplicating identical keys. Deduplication does not currently happen in the Rift format. Merging happens entirely in the archive — there is no cluster overhead.

Because merge replaces the full-backup step, the documented strategy is: take incrementals continuously and merge periodically, rather than re-running full backups against the cluster.

`--date-range <range>` accepts a comma-separated range in the same formats as `--start` / `--end`. `--threads` defaults to 1; raise it toward the client machine's CPU count.

Source: [cbbackupmgr merge](https://docs.couchbase.com/server/current/backup-restore/cbbackupmgr-merge.html)

## compact and remove

- `cbbackupmgr compact` — compacts a single backup.
- `cbbackupmgr remove` — deletes a backup repository.

## Selecting a range with --start and --end

`--start` and `--end` (on `restore`, `merge`, and `examine`) do **not** take arbitrary RFC3339 timestamps. They accept:

- **Indexes** — `--start 1 --end 2`. The first backup is 1, not 0, and `--end` is inclusive.
- **Short dates** — `day-month-year`, e.g. `--start 01-08-2026 --end 31-08-2026`. The end date is inclusive.
- **Backup names** — exactly as they appear on disk, e.g. `2026-08-13T20_01_08.894226137+01_00`.
- **Keywords** — `start` or `oldest` for the first backup in the repository; `end` or `latest` for the last.

This is why there is no minute-granularity point-in-time restore in `cbbackupmgr`: restore granularity is one backup. See `restore.md`.

Source: [cbbackupmgr restore, START AND END](https://docs.couchbase.com/server/current/backup-restore/cbbackupmgr-restore.html)

## Object-store archives

Enterprise Edition; native cloud integration was introduced in 6.6.0. Supported object stores:

| Store | Archive prefix | Notes |
|---|---|---|
| AWS S3 | `s3://` | |
| Google Cloud Storage | `gs://` | |
| Azure Blob Storage | `az://` | 7.1.2+ |

S3-compatible endpoints are reached by setting `--obj-endpoint`.

The flags are `--obj-*`, not `--s3-*`:

- `--obj-staging-dir <dir>` — **required** for cloud archives; holds local metadata during the operation. Do not use `/tmp`. Never delete individual directories inside it; remove the whole directory or nothing.
- `--obj-access-key-id`, `--obj-secret-access-key` — may be omitted when using the provider's shared config. Also available as `CB_OBJSTORE_ACCESS_KEY_ID` / the matching secret variable. For Azure the access key id field takes an account name; for GCP, a client id.
- `--obj-region`, `--obj-endpoint`, `--obj-cacert`, `--obj-no-ssl-verify`, `--obj-log-level`
- `--obj-auth-by-instance-metadata`, `--obj-auth-file`, `--obj-refresh-token`
- `--obj-read-only` — operate against an archive you cannot write to (no lockfile, no log upload).
- `--s3-force-path-style` — S3 path-style addressing, for compatible endpoints that need it.

Object lifecycle/expiry is managed on the object store side; `cbbackupmgr` does not manage object expiry. From 8.0, the Backup Service does manage retention and pruning for its own repositories.

Source: [cbbackupmgr cloud](https://docs.couchbase.com/server/current/backup-restore/cbbackupmgr-cloud.html)

## Encrypted repositories

Enterprise Edition. Encryption is configured on the repository at `config` time and then supplied to every `backup`, `merge`, `restore`, and `examine` against it.

Two modes:

- **Passphrase mode** — `--encrypted --passphrase <phrase>` or `CB_ENCRYPTION_PASSPHRASE`. The passphrase derives a key (ARGONID by default; change with `--derivation-algo`) that wraps the auto-generated repository key. The documentation explicitly discourages this in production.
- **KMS mode** — an external key manager envelopes the repository key. Supported: AWS KMS, GCP KMS, Azure Key Vault, and HashiCorp Vault Transit. Point at the key with `--km-key-url` (or `CB_KM_KEY_URL`); the URL scheme identifies the provider. Additional flags: `--km-region`, `--km-endpoint`, `--km-access-key-id`, `--km-secret-access-key`, `--km-tenant-id`, `--km-auth-file`.

The data encryption algorithm defaults to AES256GCM and can be set to AES256CBC with `--encryption-algo`.

Separately, note that **encryption-at-rest settings are not backed up or restored** — neither `--enable-bucket-config` on restore nor `--auto-create-buckets` carries them.

Source: [cbbackupmgr encryption](https://docs.couchbase.com/server/current/backup-restore/cbbackupmgr-encryption.html)

## The Backup Service

Enterprise Edition. A service you assign to one or more nodes; it uses `cbbackupmgr` technology but adds scheduling.

- **Plans** define what is backed up and on what schedule. Predefined plans: `_hourly_backups`, `_daily_backups`, `_daily_full_backups_with_incrementals`, `_weekly_full_backups_with_incrementals`. You can create custom plans with multiple tasks (Backup, Merge, and others), each with its own period and frequency.
- **Repositories** bind a plan to a bucket (or all buckets) and a storage location — Filesystem or Cloud (AWS S3).
- A filesystem location must be readable and writable by every node running the Backup Service, so it must be a shared mount, and the directory group must be set appropriately (`chgrp couchbase`, or the installing user's group for a non-root install). Use a distinct location per repository.
- For any repository the service runs **one task at a time**, holding a lock. Schedule intervals long enough for each task to finish, or the next task simply will not run.
- **8.0 adds** configurable retention periods per repository and scheduled or on-demand **pruning** of expired backups, plus dependency tracking so an incremental's prerequisites cannot be deleted by accident (overridable from the UI and REST API).
- From 8.0 the Backup Service, like other non-Data services, can be added to or removed from existing nodes dynamically.

The Backup Service can configure backup, restore, and archiving for the local cluster and restore to a remote cluster. `cbbackupmgr` can do all of those against local or remote clusters.

Sources: [Manage Backup and Restore](https://docs.couchbase.com/server/current/manage/manage-backup-and-restore/manage-backup-and-restore.html), [What's New in 8.0](https://docs.couchbase.com/server/current/introduction/whats-new.html)

## Authentication and RBAC

Use **Full Admin** or the **Data Backup & Restore** role for `cbbackupmgr`; **Full Admin** for the Backup Service. Restoring users requires the ability to create those users (Full Admin, or the matching Local/External User Security Admin); Read-Only Admin cannot restore users.

The `cbbackupmgr` reference page states the stricter position that only Full Administrators can use the tool. If you are building a least-privilege automation account around Data Backup & Restore, validate it against your exact command set first rather than assuming it covers everything.

Client-certificate (mTLS) authentication is supported as an alternative to `--username`/`--password` via `--client-cert`, `--client-key`, and the matching password flags.

## Version compatibility

`cbbackupmgr` 8.0 works with clusters on 8.0, 7.6, and 7.2. `cbbackupmgr` 7.6 works with 7.6 and 7.2. `cbbackupmgr` 7.2 works with 7.2. Check the compatibility table on the [cbbackupmgr page](https://docs.couchbase.com/server/current/backup-restore/enterprise-backup-restore.html) before mixing versions.
