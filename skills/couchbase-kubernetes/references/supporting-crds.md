# Supporting custom resources

All resources here use `apiVersion: couchbase.com/v2` and are namespaced. Field names come from the current resource reference; verify with `kubectl explain <kind>.spec` against your installed CRDs.

## Contents

- [CouchbaseBucket](#couchbasebucket)
- [Scopes and collections](#scopes-and-collections)
- [CouchbaseUser, CouchbaseGroup, CouchbaseRoleBinding](#couchbaseuser-couchbasegroup-couchbaserolebinding)
- [CouchbaseBackup](#couchbasebackup)
- [CouchbaseBackupRestore](#couchbasebackuprestore)
- [XDCR: remote clusters and CouchbaseReplication](#xdcr-remote-clusters-and-couchbasereplication)
- [CouchbaseAutoscaler](#couchbaseautoscaler)

## CouchbaseBucket

```yaml
apiVersion: couchbase.com/v2
kind: CouchbaseBucket
metadata:
  name: orders
  namespace: couchbase-prod
spec:
  memoryQuota: 4Gi
  replicas: 1                      # 0-3, default 1
  evictionPolicy: valueOnly        # valueOnly (default) | fullEviction
  conflictResolution: seqno        # seqno (default) | lww
  compressionMode: passive         # off | passive (default) | active
  storageBackend: magma            # couchstore | magma
  minimumDurability: majority      # none | majority | majorityAndPersistActive | persistToMajority
  enableFlush: false               # true only in development
  maxTTL: 0                        # 0 = no bucket-level expiry
```

Other fields worth knowing: `memoryHighWatermark` (51–90, default 85) and `memoryLowWatermark` (50–89, default 75), which are the ejection watermarks `couchbase-observability` refers to; `numVBuckets` (128 or 1024, magma only); `rank`; `enableIndexReplica`; `enableCrossClusterVersioning`; `warmupBehavior` (`none`, `background`, `blocking` — new in Couchbase Server 8.0).

`ioPriority` accepts `low` and `high`, but note that **in Couchbase Server 8.0 bucket priority no longer changes behaviour** — the background task scheduler was replaced and the setting is inert. Do not present it as a tuning lever on 8.0.

`conflictResolution` cannot be changed after the bucket is created. Choose `lww` only if you understand the data-loss semantics under clock skew; `seqno` is the default for good reason.

For the Operator to reconcile buckets at all, the cluster must opt in:

```yaml
# in CouchbaseCluster
spec:
  buckets:
    managed: true
```

With `managed: true`, a bucket that exists in Couchbase but has no `CouchbaseBucket` resource is a candidate for deletion by the Operator. Adopt existing buckets deliberately rather than switching this on over a live cluster.

`CouchbaseEphemeralBucket` covers ephemeral buckets. `CouchbaseMemcachedBucket` covers Memcached buckets, which are **7.x only — Couchbase Server 8.0 removed Memcached buckets entirely, and an upgrade fails if any are present.** Replace them with ephemeral buckets before upgrading.

## Scopes and collections

```yaml
apiVersion: couchbase.com/v2
kind: CouchbaseScope
metadata:
  name: sales
  namespace: couchbase-prod
spec:
  name: sales
  collections:
    managed: true
---
apiVersion: couchbase.com/v2
kind: CouchbaseCollection
metadata:
  name: invoices
  namespace: couchbase-prod
spec:
  name: invoices
  maxTTL: 0
```

`CouchbaseScopeGroup` and `CouchbaseCollectionGroup` declare several scopes or collections in one resource, which is considerably less YAML when a bucket has many collections following the same pattern.

Resources are wired together by label selection rather than by name references — a bucket selects its scopes, a scope selects its collections. Get the labels right or the Operator will not associate them, and the failure is silent.

## CouchbaseUser, CouchbaseGroup, CouchbaseRoleBinding

```yaml
apiVersion: couchbase.com/v2
kind: CouchbaseUser
metadata:
  name: orders-service
  namespace: couchbase-prod
spec:
  authSecret: orders-service-credentials   # secret with a "password" key
  authDomain: local
  roles:
    - name: data_reader
      bucket: orders
      scope: sales
      collection: invoices
    - name: data_writer
      bucket: orders
      scope: sales
      collection: invoices
    - name: query_select
      bucket: orders
      scope: sales
      collection: invoices
```

The `bucket` / `scope` / `collection` fields are how scoped RBAC is expressed here — the same narrowing described in `couchbase-security-hardening/references/rbac.md`. Use the narrowest level the role supports. Cluster-wide roles such as `cluster_admin` and `external_stats_reader` take no bucket.

```yaml
apiVersion: couchbase.com/v2
kind: CouchbaseGroup
metadata:
  name: reporting
spec:
  roles:
    - name: query_select
      bucket: orders
---
apiVersion: couchbase.com/v2
kind: CouchbaseRoleBinding
metadata:
  name: analyst-reporting
spec:
  subjects:
    - kind: CouchbaseUser
      name: analyst
  roleRef:
    kind: CouchbaseGroup
    name: reporting
```

This requires `spec.security.rbac.managed: true` on the `CouchbaseCluster`.

## CouchbaseBackup

```yaml
apiVersion: couchbase.com/v2
kind: CouchbaseBackup
metadata:
  name: daily-backup
  namespace: couchbase-prod
spec:
  strategy: full_incremental
  full:
    schedule: "0 2 * * 0"
  incremental:
    schedule: "0 2 * * 1-6"
  merge:
    schedule: "0 4 * * 0"
  backupRetention: 720h        # duration; default 720h
  logRetention: 168h
  size: 200Gi                  # default 20Gi
  storageClassName: <your-storage-class>
  threads: 1
  backoffLimit: 2
```

`strategy` accepts `full_only`, `full_incremental` (default), `periodic_merge`, `immediate_incremental` and `immediate_full`. The two `immediate_*` values trigger a backup at once rather than describing a schedule — useful for an ad-hoc backup before a risky change.

`backupRetention` is a duration, not a count.

For object storage, use `objectStore` rather than the older `s3bucket` field, which is **deprecated**:

```yaml
spec:
  objectStore:
    uri: s3://bucket/prefix      # also az:// and gs://
    secret: object-store-credentials
    useIAM: true                 # use instance metadata instead of a secret
    endpoint:
      url: <custom endpoint>     # for S3-compatible stores
```

`spec.services` and `spec.data` narrow what is backed up — by service, and by bucket, scope or collection.

An operator-scheduled backup is not a backup strategy. Restore rehearsal, off-site copies and archive encryption are in `couchbase-backup-restore`; this resource only runs the job.

## CouchbaseBackupRestore

```yaml
apiVersion: couchbase.com/v2
kind: CouchbaseBackupRestore
metadata:
  name: restore-run
  namespace: couchbase-prod
spec:
  backup: daily-backup
  repo: <repository>
  start:
    int: 1          # or .str for a timestamp
  end:
    int: 5
```

The restore runs once when the resource is created. Leaving a completed restore resource in the namespace is untidy but harmless; recreating it re-runs the restore, which is not.

## XDCR: remote clusters and CouchbaseReplication

Remote clusters are **not** a separate resource. They are declared on the `CouchbaseCluster`:

```yaml
# in CouchbaseCluster
spec:
  xdcr:
    managed: true
    remoteClusters:
      - name: dr
        uuid: <remote cluster's status.clusterId>
        hostname: <remote address>
        authenticationSecret: dr-credentials
        tls:
          secret: dr-ca
        replications:
          selector:
            matchLabels:
              replication: to-dr
```

Each replication is a `CouchbaseReplication`, matched to a remote cluster by label:

```yaml
apiVersion: couchbase.com/v2
kind: CouchbaseReplication
metadata:
  name: orders-to-dr
  namespace: couchbase-prod
  labels:
    replication: to-dr
spec:
  bucket: orders
  remoteBucket: orders
  compressionType: Auto
```

Always set the label and the selector. Without them the Operator has to guess which remote cluster a replication belongs to, and the resolution is ambiguous when there is more than one.

The spec carries the full XDCR tuning surface — `filterExpression` and the `filter*` family, `explicitMapping` for scope and collection mapping, `priority`, `paused`, the nozzle and batch settings, `networkUsageLimit`, `conflictLogging`, `mobile`, and more. Tune these from `couchbase-xdcr` rather than from defaults you half-remember; most of them should stay unset.

## CouchbaseAutoscaler

`CouchbaseAutoscaler` exposes a server class to the Kubernetes Horizontal Pod Autoscaler, so a class can scale on a metric. Related `CouchbaseCluster` fields are `spec.enablePreviewScaling` and `spec.autoscaleStabilizationPeriod`.

Autoscaling a stateful database is not autoscaling a web tier: adding a Data Service pod triggers a rebalance that moves data over the network, and removing one triggers another. Set the stabilisation period generously, and prefer autoscaling on the Query Service — which is stateless and CPU-bound — over the Data Service. Check the preview status of these features for your Operator release before depending on them in production.
