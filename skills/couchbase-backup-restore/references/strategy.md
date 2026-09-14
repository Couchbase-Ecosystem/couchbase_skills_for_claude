# Backup strategy

## Contents

- [Backup types](#backup-types)
- [Merge instead of repeated full backups](#merge-instead-of-repeated-full-backups)
- [Choosing a schedule](#choosing-a-schedule)
- [What gets backed up](#what-gets-backed-up)
- [Object-store archives](#object-store-archives)
- [Encryption](#encryption)
- [Retention and pruning](#retention-and-pruning)
- [Backup verification](#backup-verification)

## Backup types

**Full backup.** A complete copy of everything in the repository's scope. Self-contained: restoring from it requires nothing else. The first backup into a new `cbbackupmgr` repository is implicitly full; `--full-backup` forces another one, re-streaming all data at the cost of time and disk.

**Incremental.** Everything after the first is incremental by default, capturing the mutations since the previous backup in that repository. Fast and small, but restoring a given backup requires the preceding full plus every incremental up to it. The documentation calls these incremental; do not relabel them.

**Merge (Enterprise Edition).** Combines a run of backups into a single full backup *inside the archive*, with no cluster involvement. It always reclaims the per-backup metadata overhead and, in the SQLite format, deduplicates identical keys across the merged backups. Deduplication does not currently happen in the Rift format.

## Merge instead of repeated full backups

The documented strategy is not "weekly full, hourly incremental". It is: take incrementals continuously, and **use `merge` to replace the full-backup step**, converting multiple incrementals into a single full backup in the archive. This avoids re-streaming the whole dataset off the cluster on a schedule.

Reserve forced `--full-backup` runs for cases where you want a fresh, independently restorable generation on the cluster's terms — for example immediately before a major upgrade.

In Community Edition there is no `merge`, so forced fulls (or a fresh repository) are the only way to bound chain length.

Source: [cbbackupmgr merge](https://docs.couchbase.com/server/current/backup-restore/cbbackupmgr-merge.html)

## Choosing a schedule

Two variables matter: how often you take an incremental (which sets RPO) and how long the restore chain is allowed to get (which affects RTO and blast radius).

With the Backup Service, this is expressed as a **plan** with one or more **tasks**, each with a period (Weekly Calendar, Hours, Minutes) and a frequency. Predefined plans are `_hourly_backups`, `_daily_backups`, `_daily_full_backups_with_incrementals`, and `_weekly_full_backups_with_incrementals`. A plan can mix Backup and Merge tasks so that consolidation happens on its own cadence.

Important operational constraint: for a given repository the Backup Service runs **one task at a time** under a lock. If a scheduled task fires while the previous one is still running, the new task simply does not run. Set intervals with headroom over the observed task duration.

Always take a full backup before a planned upgrade or a bulk data change, and hold it until the change is confirmed stable.

## What gets backed up

Configured on the repository at `cbbackupmgr config` time and inherited by every backup in it.

- **By default:** data and metadata — bucket configuration, GSI definitions, Search indexes and aliases, views, Eventing functions, Query SQL++ user-defined functions, analytics collections and indexes for local links and synonyms, and (7.6+) scope and collection definitions. On clusters running 7.6+, the `_system` scope is included too.
- **Not by default:** users and user groups. Opt in with `--enable-users`; this requires Couchbase Server 7.6+ and the resulting backup contains hashed passwords.
- **Never:** Query function libraries (user-created JavaScript libraries), and encryption-at-rest settings. Back the former up separately; the latter must be reconfigured on the target.
- **Metadata only:** `--disable-data` gives you a settings-transfer backup, which is a clean way to stand up a new cluster with matching configuration.

Narrow the data with `--include-data` / `--exclude-data` using collection strings. Scope/collection granularity is Enterprise Edition.

## Object-store archives

Enterprise Edition; introduced in Couchbase Server 6.6.0. Prefix the archive path with `s3://`, `gs://`, or (7.1.2+) `az://`. S3-compatible endpoints work via `--obj-endpoint`.

```bash
cbbackupmgr config \
    --archive s3://my-backup-bucket/couchbase-backups \
    --repo prod-cluster \
    --obj-region <region> \
    --obj-staging-dir /var/lib/cbbackup-staging
```

Credentials come from `--obj-access-key-id` / `--obj-secret-access-key`, the `CB_OBJSTORE_*` environment variables, instance metadata (`--obj-auth-by-instance-metadata`), an auth file (`--obj-auth-file`), or the provider's own shared config.

Operational notes:

- `--obj-staging-dir` is required and must not be `/tmp`. Treat it as opaque: delete the whole directory or none of it.
- Object expiry is the object store's job. Configure lifecycle rules there; `cbbackupmgr` does not manage object expiry. (The Backup Service does manage retention for its own repositories from 8.0.)
- Backup to object storage moves the full change set over the network. Make sure the host running the backup has the egress capacity, and prefer a dedicated backup host over a busy data node.
- `--obj-read-only` lets you read an archive you lack write permission on, at the cost of no log upload — keep local logs if you use it.

The Backup Service also supports cloud storage, with AWS S3 as the documented option in its repository dialog.

## Encryption

Enterprise Edition. Set on the repository at `config` time with `--encrypted`, then supplied to every operation on it.

- **KMS mode** is the production path: an external key manager envelopes the repository key. AWS KMS, GCP KMS, Azure Key Vault, and HashiCorp Vault Transit are supported. The key is identified by `--km-key-url` / `CB_KM_KEY_URL`, whose scheme picks the provider.
- **Passphrase mode** (`--passphrase` / `CB_ENCRYPTION_PASSPHRASE`) is explicitly documented as development-only.
- Data encryption defaults to AES256GCM; AES256CBC is available via `--encryption-algo`. Key derivation from a passphrase defaults to ARGONID (`--derivation-algo`).

Separately, Couchbase Server 8.0 Enterprise Edition adds **native encryption at rest** for bucket, log, audit, and configuration data, with third-party KMS support. That is a cluster feature, not a backup feature — backups of an encrypted cluster still need their own repository encryption, and encryption-at-rest settings are not restored.

## Retention and pruning

From **8.0**, the Backup Service supports configurable retention periods per repository and automatic **pruning** of backups past their retention, either on a schedule or triggered on demand. It also tracks incremental dependencies: a backup another incremental still needs cannot be deleted, though that protection can be overridden from the UI and REST API.

Before 8.0, and for plain `cbbackupmgr` archives at any version, retention is your responsibility: merge older backups into a single full, then delete the superseded backups, and put lifecycle rules on the object store if the archive lives there.

## Backup verification

Never assume a backup is valid without checking it.

1. **`cbbackupmgr info`** after every backup run. It reports the archive, repositories, backups, and their contents without needing a running cluster. This is the routine automated check.
2. **`cbbackupmgr examine`** (Enterprise Edition) when you need to prove a *specific* key is recoverable — for example after an incident, before telling someone their data is retrievable. It traces one key's history across backups; it is not a bulk verifier.
3. **Restore into a staging cluster** on a regular cadence, and after any major schema or data change. Run the application's test suite against the result. This is the only check that validates the whole path.
4. **Count parity** after a test restore: compare `SELECT COUNT(*)` per keyspace against the item counts `cbbackupmgr info` reports for the backup.

Scheduled tasks give a false sense of security if nobody reads their outcome. Alert on backup task failure and on a repository whose newest backup is older than the plan interval.
