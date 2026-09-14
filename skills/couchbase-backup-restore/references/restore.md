# Restore

## Contents

- [Restore granularity: there is no minute-level point in time](#restore-granularity-there-is-no-minute-level-point-in-time)
- [Full cluster restore](#full-cluster-restore)
- [Restoring a subset: buckets, scopes, collections](#restoring-a-subset-buckets-scopes-collections)
- [Remapping with --map-data](#remapping-with---map-data)
- [Creating the destination](#creating-the-destination)
- [Conflict resolution on restore](#conflict-resolution-on-restore)
- [Users and groups](#users-and-groups)
- [Restoring into Capella](#restoring-into-capella)
- [Recovering individual documents](#recovering-individual-documents)
- [Replacing TTLs](#replacing-ttls)
- [Cross-cluster versioning metadata](#cross-cluster-versioning-metadata)
- [Restore checklist](#restore-checklist)

## Restore granularity: there is no minute-level point in time

`cbbackupmgr restore --start`/`--end` select a **range of backups**, not a wall-clock instant. They take backup indexes (1-based, `--end` inclusive), short dates in `day-month-year` form, backup names as they appear on disk, or the keywords `start`/`oldest` and `end`/`latest`.

So the achievable recovery point is "the state as of backup N", and your RPO is your backup interval. Do not promise a customer restore "to the minute" from `cbbackupmgr`. If they need finer recovery, the levers are a shorter incremental interval and, for logical errors, XDCR-independent copies.

Source: [cbbackupmgr restore](https://docs.couchbase.com/server/current/backup-restore/cbbackupmgr-restore.html)

## Full cluster restore

```bash
cbbackupmgr restore \
    --archive /backup/couchbase-archive \
    --repo prod-cluster \
    --cluster couchbase://10.0.0.1 \
    --username <restore-user> \
    --password <pass> \
    --start oldest \
    --end latest
```

Omitting `--start`/`--end` restores the repository's default range.

Frequently used options:

- `-t, --threads <num>` — concurrent clients. **Defaults to 1.** Fewer clients means a slower restore with less cluster impact; do not exceed the CPU count of the restoring host.
- `--resume` — continue an interrupted restore from where it stopped.
- `--purge` — **discard the persisted progress of a failed restore and start from zero.** It does *not* delete documents from the destination and it does not remove backup data. There is no `cbbackupmgr` flag that deletes destination documents absent from the backup; restore is additive/overwriting, never subtractive.
- `--restore-partial-backups` — allow the restore to proceed when the final backup in range is incomplete. Incompatible with `--obj-read-only`.
- `--continue-on-cs-failure` — keep going past a checksum validation failure instead of failing fast.
- `--exclude-tombstones`, `--exclude-expired` — skip deletion markers and already-expired items; skipping expired items reduces restore time and cluster load.
- `--no-progress-bar` — for automated jobs.

To skip metadata classes on restore, use the `--disable-*` family (`--disable-gsi-indexes`, `--disable-ft-indexes`, `--disable-ft-alias`, `--disable-views`, `--disable-data`, `--disable-analytics`, `--disable-cluster-analytics`, `--disable-eventing`, `--disable-bucket-query`, `--disable-cluster-query`). There is no `--no-indexes` flag. Note `--disable-data` still creates scopes and collections.

`--enable-bucket-config` restores bucket configuration. Encryption-at-rest settings are never backed up or restored.

## Restoring a subset: buckets, scopes, collections

Use collection strings with `--include-data` or `--exclude-data` (mutually exclusive). Scope and collection granularity is an **Enterprise Edition** feature; Community Edition restores at bucket level only.

```bash
# One bucket
cbbackupmgr restore ... --include-data orders

# One collection
cbbackupmgr restore ... --include-data orders.my-scope.active-orders

# Everything except one scope
cbbackupmgr restore ... --exclude-data orders.internal
```

There are no `--include-buckets`, `--include-scopes`, or `--include-collections` flags.

You can further narrow by content with `--filter-keys <regexp>` and `--filter-values <regexp>`, both using [RE2 syntax](https://github.com/google/re2/wiki/Syntax), and by vBucket with `--vbucket-filter`.

## Remapping with --map-data

```bash
cbbackupmgr restore ... \
    --include-data orders \
    --map-data orders=orders-restored
```

`--map-data` takes a comma-separated list of collection-string mappings. The documented allowances are:

- a bucket can be mapped to a bucket;
- a scope can be mapped to another scope **within the same bucket**;
- a collection can be mapped to another collection **within the same scope of the same bucket**.

If you remap a bucket into a collection, only Data service data is restored; all other services are skipped.

Two helpers around collection drift:

- `--autoremove-collections` — delete scopes/collections that the backup records as deleted.
- `--auto-resolve-conflicts` — remap all scopes/collections by name. Use only when you are certain same-named collections serve the same purpose.
- `--preserve-collection-settings` — keep the target cluster's existing collection settings instead of overwriting them from the backup (the default is to overwrite).

If a scope in the backup has a different scope ID on the cluster, a manual remap with `--map-data bucket.scope=bucket.scope` is required.

## Creating the destination

`--auto-create-buckets` creates destination buckets that are not present on the server. Encryption-at-rest settings are not carried over. Without that flag, the destination bucket must already exist, and you are responsible for matching quota, replica count, and storage backend.

## Conflict resolution on restore

By default, restore uses Couchbase's conflict resolution: if the cluster holds newer data than the backup, the cluster's version wins and is not overwritten. `--force-updates` overrides that and overwrites cluster data even when it is newer. Use it deliberately — it is the flag that makes a restore authoritative over live writes.

## Users and groups

- `--enable-users` — restore cluster-level users. Requires Couchbase Server 7.6+ on both sides; ignored on earlier versions. The default behaviour is to **skip users that already exist**.
- `--overwrite-users` — overwrite existing users. Use together with `--enable-users`.
- A user that exists in the backup but not on the cluster is unaffected by these flags in the sense that nothing on the cluster is altered for it beyond the restore itself; a user present on the cluster but not in the backup is never removed.
- Restoring users requires permission to create those users: Full Admin restores anything; Local User Security Admin can restore local users; External User Security Admin can restore external users; Read-Only Admin cannot restore users at all.

## Restoring into Capella

`--capella` on restore skips the services Capella does not support — analytics, cluster analytics, bucket query, cluster query, views, and users — so an on-premises backup can be restored into a Capella cluster. Note the same flag exists on `config`, to build a Capella-compatible repository from the start.

## Recovering individual documents

`cbbackupmgr` has no single-document restore mode. Two workable routes:

**Route 1 — `examine`, then re-apply (Enterprise Edition).**
`examine` finds a key and prints its timeline across backups, including the value:

```bash
cbbackupmgr examine \
    --archive /backup/couchbase-archive \
    --repo prod-cluster \
    --collection-string orders.my-scope.active-orders \
    --key "order::abc123" \
    --json
```

You then re-apply the value through the SDK, the CLI, or SQL++. This is exact but manual, and it only works when you already know the key.

**Route 2 — restore into an isolated keyspace, then copy back.**
Restore the relevant range into a separate bucket or collection with `--map-data`, then copy the documents you need with SQL++:

```sql
INSERT INTO `orders`.`my-scope`.`active-orders` (KEY k, VALUE r)
SELECT META(r).id AS k, r
FROM `orders-recovery`.`my-scope`.`active-orders` AS r
WHERE META(r).id = "order::abc123";
```

## Replacing TTLs

`--replace-ttl <none|all|expired>` with `--replace-ttl-with <timestamp>` rewrites expiry on restore. `--replace-ttl-with` takes an RFC3339 timestamp or `0` to remove expiry entirely. The client converts RFC3339 to a Unix timestamp, so client and server clocks must agree or expiry will be wrong.

## Cross-cluster versioning metadata

If a source bucket had `enableCrossClusterVersioning` enabled, its documents carry XDCR's Hybrid Logical Vector metadata in the `_vv` xattr. Since that bucket property cannot be disabled once set, the documented way to shed the metadata is to restore into a bucket where `enableCrossClusterVersioning` is `false`, using `cbbackupmgr restore --disable-hlv` (8.0+) to strip the xattr. Restoring into such a bucket without `--disable-hlv` is not sufficient. See [XDCR enableCrossClusterVersioning](https://docs.couchbase.com/server/current/learn/clusters-and-availability/xdcr-enable-crossclusterversioning.html).

## Restore checklist

1. **Notify stakeholders.** A restore over a live cluster overwrites data.
2. **Drain traffic or enter maintenance mode** if you are overwriting live data.
3. **`cbbackupmgr info`** the repository first — confirm the backups, their range, and their contents. Use `examine` if you need to prove a specific key is present.
4. **Rehearse on staging** for anything schema-changing or unfamiliar.
5. **Use `--map-data`** to land the restore in a non-production keyspace when you want to verify before going live.
6. **Decide on `--force-updates`** consciously: without it, newer cluster data survives.
7. **Check counts after restore** — compare `SELECT COUNT(*) FROM <keyspace>` against the item counts reported by `cbbackupmgr info`.
8. **Build indexes.** Restored GSI definitions are not automatically online; issue `BUILD INDEX` for the deferred indexes in each affected keyspace.
