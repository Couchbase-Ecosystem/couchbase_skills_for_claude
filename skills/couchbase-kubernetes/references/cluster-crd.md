# The CouchbaseCluster resource

`CouchbaseCluster` is the definition of the cluster itself. Field names here come from the current resource reference; check `kubectl explain couchbasecluster.spec` against your installed CRDs before committing a manifest, because the schema changes between Operator releases.

## Contents

- [Top-level spec fields](#top-level-spec-fields)
- [An annotated example](#an-annotated-example)
- [Server classes and services](#server-classes-and-services)
- [Server groups and zone awareness](#server-groups-and-zone-awareness)
- [Resources and QoS](#resources-and-qos)
- [Storage and volume mounts](#storage-and-volume-mounts)
- [Upgrade configuration](#upgrade-configuration)

## Top-level spec fields

| Field | Purpose |
|---|---|
| `image` | Couchbase Server container image |
| `security` | Admin credentials secret, RBAC management, LDAP, encryption |
| `securityContext` | Pod security context, including `fsGroup` |
| `networking` | DNS, TLS, exposed services, admin console |
| `servers` | Server classes — size, services, resources, storage |
| `serverGroups` | Default set of server groups (zones) for all server classes |
| `cluster` | Cluster-wide settings: memory quotas, auto-failover, index settings |
| `volumeClaimTemplates` | Persistent volume claim templates referenced by `volumeMounts` |
| `enableOnlineVolumeExpansion` | Allows volumes to be expanded in place |
| `antiAffinity` | Prevents multiple Couchbase pods landing on the same Kubernetes node |
| `autoResourceAllocation` | Automatic population of resource requests |
| `upgrade` | Upgrade strategy and process |
| `backup` | Operator-managed backup configuration |
| `xdcr` | XDCR remote cluster references |
| `buckets` | Whether the Operator manages buckets from `CouchbaseBucket` resources |
| `logging` | Server and audit logging configuration |
| `monitoring` | Prometheus configuration (legacy exporter path; see `operations.md`) |
| `hibernate` | Scales the cluster to zero while preserving volumes |
| `migration` | Migration settings |
| `enablePreviewScaling`, `autoscaleStabilizationPeriod` | Autoscaling controls |

## An annotated example

```yaml
apiVersion: couchbase.com/v2
kind: CouchbaseCluster
metadata:
  name: couchbase-prod
  namespace: couchbase-prod
spec:
  image: couchbase/server:<supported-EE-tag>

  security:
    adminSecret: couchbase-operator-credentials
    rbac:
      managed: true          # Operator reconciles CouchbaseUser / CouchbaseGroup

  securityContext:
    fsGroup: 1000            # omit on OpenShift

  networking:
    tls:
      static:
        serverSecret: couchbase-server-tls
        operatorSecret: couchbase-operator-tls
    exposeAdminConsole: true

  antiAffinity: true
  enableOnlineVolumeExpansion: true

  # Default zones for every server class
  serverGroups:
    - zone-a
    - zone-b
    - zone-c

  servers:
    - name: data
      size: 3
      services:
        - data
      # inherits spec.serverGroups
      resources:
        requests: { cpu: "4", memory: "16Gi" }
        limits:   { cpu: "4", memory: "16Gi" }
      volumeMounts:
        default: couchbase-default
        data: couchbase-data

    - name: index-query
      size: 3
      services:
        - index
        - query
      resources:
        requests: { cpu: "8", memory: "32Gi" }
        limits:   { cpu: "8", memory: "32Gi" }
      volumeMounts:
        default: couchbase-default
        index: couchbase-index

  volumeClaimTemplates:
    - metadata:
        name: couchbase-default
      spec:
        storageClassName: <your-storage-class>
        accessModes: [ReadWriteOnce]
        resources:
          requests:
            storage: 50Gi

    - metadata:
        name: couchbase-data
      spec:
        storageClassName: <your-storage-class>
        accessModes: [ReadWriteOnce]
        resources:
          requests:
            storage: 500Gi

    - metadata:
        name: couchbase-index
      spec:
        storageClassName: <your-storage-class>
        accessModes: [ReadWriteOnce]
        resources:
          requests:
            storage: 200Gi
```

Pin `image` to a specific Couchbase Server Enterprise Edition tag that the Operator release supports. Never use a floating tag — image resolution changing under a pod restart is an unplanned upgrade.

## Server classes and services

Each entry in `spec.servers` is a **server class**: a set of identically configured pods running the same services.

**Small — all services co-located:**
```yaml
servers:
  - name: all-services
    size: 3
    services: [data, query, index, search, eventing, analytics, backup]
```

**Medium — data separated from query and index:**
```yaml
servers:
  - name: data
    size: 3
    services: [data]
  - name: query-index
    size: 2
    services: [query, index]
```

**Large — one service per class**, so each can be sized and scaled on its own resource profile.

Multi-dimensional scaling is the main reason to run Couchbase this way: the Query Service is CPU-bound, the Index Service is memory-bound, and the Data Service is memory- and disk-bound. Co-locating them means over-provisioning two of the three.

Analytics in a Couchbase Server cluster is the Analytics Service. Couchbase Enterprise Analytics is a separate self-managed product, and Capella Analytics is its cloud counterpart — neither is configured through this field.

## Server groups and zone awareness

`spec.serverGroups` sets the default set of groups available to every server class. A server class can override it with its own `spec.servers[].serverGroups`, which **replaces** the global default for that class rather than adding to it — useful when a class is sized so that it cannot balance evenly across the default set.

The Operator maps server groups onto Kubernetes nodes through the standard topology label:

```
topology.kubernetes.io/zone
```

The values are your own failure-domain identifiers; they must match the labels actually present on your nodes. Verify with `kubectl get nodes --show-labels` before deploying — server groups that name zones no labelled node reports leave pods `Pending` with no obvious explanation.

**Minimum for genuine zone tolerance:** at least three groups, at least one data pod in each, and a replica count of at least one. Replicas alone are not zone tolerance — without server groups, Couchbase does not know that two pods share a failure domain, and can place a document's active and replica copies in the same zone.

## Resources and QoS

**Set requests and limits to the same values** so the pod lands in the Guaranteed QoS class. Couchbase is a database; a pod that bursts above its request and is then OOM-killed under node pressure is a node failure event, and the Operator will have to fail it over and rebalance.

Size pod memory as the sum of the Couchbase service memory quotas plus headroom for the operating system and for Couchbase processes outside the managed quotas. Derive that headroom from the sizing guidance in `couchbase-sizing` and from your own measurements, not from a remembered constant.

`spec.autoResourceAllocation` can populate resource requests automatically; it is a convenience, not a substitute for sizing.

## Storage and volume mounts

Each server class maps named mounts to volume claim templates:

| Mount | Holds |
|---|---|
| `default` | Anything not separately mapped, including configuration and logs |
| `data` | Data service files |
| `index` | Index service files |
| `analytics` | Analytics service files |

The point of separate mounts is that the services have genuinely different storage profiles — the documentation's own framing is high-performance disk for data and index, with configuration and logs on cheaper media.

**Give logs somewhere to go other than the data volume.** Logs filling the data volume is a well-known way to take a node down, and it is entirely avoidable.

Size volumes from the sizing skill's arithmetic on your actual working set, retention and compaction overhead.

Local persistent volumes are supported but carry real operational cost: upgrades need extra volumes during pod replacement, node-level management is manual, and a node going offline can require administrator intervention. Prefer network-attached block storage unless you have a specific reason not to.

## Upgrade configuration

Upgrade behaviour lives under `spec.upgrade`, not in a top-level `upgradeStrategy` field:

| Field | Values |
|---|---|
| `spec.upgrade.upgradeStrategy` | `RollingUpgrade` (pods handled sequentially, in controlled batches) or `ImmediateUpgrade` (all pods concurrently) |
| `spec.upgrade.upgradeProcess` | `SwapRebalance` (default) or `InPlaceUpgrade` |
| `spec.upgrade.rollingUpgrade` | Batching controls for the rolling strategy |

`SwapRebalance` creates new pods, rebalances data onto them, then deletes the originals — more resource-hungry, less disruptive. `InPlaceUpgrade` fails pods over, detaches their volumes, replaces the pods with the new version, and reattaches the volumes — faster, but higher risk, and restricted to clusters with more than one Data Service node.

`ImmediateUpgrade` takes the cluster down. It is for development environments.

See `operations.md` for running an upgrade.
