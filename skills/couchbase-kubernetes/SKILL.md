---
name: couchbase-kubernetes
description: "Deploy and operate Couchbase Server on Kubernetes with the Couchbase Kubernetes (Autonomous) Operator. Use whenever the user asks about the Couchbase Operator or CAO, the CouchbaseCluster CRD, Couchbase on Kubernetes or OpenShift, the Couchbase Helm chart or the cao CLI, CouchbaseBucket, CouchbaseUser, CouchbaseGroup, CouchbaseRoleBinding, CouchbaseScope, CouchbaseCollection, CouchbaseBackup, CouchbaseBackupRestore, CouchbaseReplication or CouchbaseAutoscaler resources, server groups and availability-zone awareness, persistent volumes and online volume expansion, pod resources and anti-affinity, rolling upgrades through the operator, operator RBAC and the admission controller, hibernation, or Prometheus scraping of Couchbase pods. Covers the supported Kubernetes, OpenShift and Couchbase Server version matrix, which is Enterprise Edition only. Distinct from couchbase-capella, which is managed and has no Kubernetes."
license: Apache-2.0
---

# Couchbase on Kubernetes (Couchbase Operator)

Deploying and operating Couchbase Server on Kubernetes with the Couchbase Kubernetes Operator, also called the Couchbase Autonomous Operator and abbreviated CAO. The current documentation uses "Kubernetes Operator" as the primary name; both refer to the same product, and the binaries and chart are still named `couchbase-operator`.

Distinct from:
- `couchbase-capella` — fully managed, no Kubernetes involved
- `couchbase-upgrade` — upgrading Couchbase Server outside Kubernetes
- `couchbase-sizing` — the capacity arithmetic, which applies unchanged; this skill covers only the Kubernetes mechanics

**The Operator manages Couchbase Server Enterprise Edition. It is not a route to running Community Edition on Kubernetes.**

## Verify the version matrix first

The Operator, Kubernetes, OpenShift and Couchbase Server versions are tightly coupled, and all four move. As of Operator 2.9.x:

| Component | Supported |
|---|---|
| Couchbase Operator | 2.9, with patch releases through 2.9.3 |
| Couchbase Server | Enterprise Edition 7.2 through 8.0 |
| Kubernetes | Open source 1.31 – 1.35 |
| OpenShift | Red Hat OpenShift Container Platform 4.18 – 4.20 |

Couchbase Server 8.0 requires Operator 2.8.1 or later, with full feature support in 2.9.x.

Certified managed platforms named in the documentation include Amazon EKS, Google GKE and Microsoft AKS, along with K3s and Bottlerocket OS. Both ARM and AMD64 architectures are supported, but not mixed within a single cluster. Couchbase Server 8.0 vector-search workloads want AVX2 instructions available on the nodes.

**Always re-read the platform support page before planning.** This matrix is the fastest-moving fact in this skill, the Kubernetes range moves roughly every release, and deploying outside it is unsupported rather than merely untested. Do not quote it from memory, including from this table.

## When this skill applies

- "How do I deploy Couchbase on Kubernetes or OpenShift?"
- "How do I install the Operator — Helm chart or the `cao` CLI?"
- "How do I write a CouchbaseCluster resource? What fields does it take?"
- "How do I get availability-zone awareness?"
- "How do I size and expand persistent volumes?"
- "How do I roll out a new Couchbase Server version through the Operator?"
- "How do buckets, scopes, collections, users and backups work as custom resources?"
- "How do I scrape Couchbase pods with Prometheus?"

## Pick the right reference

| Question | Read |
|---|---|
| Installing the Operator — Helm, the `cao` CLI, the admission controller, RBAC, secrets, storage classes | `references/installation.md` |
| CouchbaseCluster — topology, services, server groups, resources, storage, TLS, security | `references/cluster-crd.md` |
| Buckets, scopes, collections, users, groups, backups, XDCR and autoscaling as custom resources | `references/supporting-crds.md` |
| Upgrades, scaling, volume expansion, Prometheus, hibernation, troubleshooting | `references/operations.md` |

## Three core principles

**The Operator reconciles; you do not.** When the Operator manages a cluster, changes made directly through the Web Console or REST API are reverted at the next reconciliation. Every change goes through the custom resources. This is the single most common cause of "my change disappeared."

**Persistent volumes are the decision you cannot easily undo.** Data, Index and Analytics nodes need volumes that outlive their pods. You can expand a volume online if the Operator and storage class are configured for it, but you can never shrink one. Use a storage class with volume expansion enabled and late binding so volumes land in the right zone.

**Server groups are what makes availability-zone awareness real.** Declare server groups aligned to your Kubernetes topology labels, and assign server classes to them. Without this the scheduler is free to put every Couchbase pod in one zone, and a single zone failure takes the cluster down despite the replica count suggesting otherwise.

## Custom resource types

All Operator resources use API version `couchbase.com/v2` and are namespaced.

| Kind | What it manages |
|---|---|
| `CouchbaseCluster` | The cluster — servers, services, networking, TLS, security, server groups, backup, XDCR remote clusters |
| `CouchbaseBucket` | Bucket lifecycle |
| `CouchbaseEphemeralBucket` | Ephemeral (non-persistent) buckets |
| `CouchbaseScope` / `CouchbaseScopeGroup` | Scopes within a bucket |
| `CouchbaseCollection` / `CouchbaseCollectionGroup` | Collections within a scope |
| `CouchbaseUser` | Couchbase users and their roles |
| `CouchbaseGroup` | Role groups |
| `CouchbaseRoleBinding` | Binds users to groups |
| `CouchbaseBackup` | Scheduled backups |
| `CouchbaseBackupRestore` | Restores |
| `CouchbaseReplication` | An XDCR replication |
| `CouchbaseAutoscaler` | Horizontal autoscaling of a server class |
| `CouchbaseMemcachedBucket` | Memcached buckets — **7.x only; Memcached buckets were removed in Couchbase Server 8.0** |

Two naming corrections worth stating plainly, because both appear in older material: the XDCR resource is `CouchbaseReplication`, not `CouchbaseReplicationRepresentation`, and remote clusters are **not** a separate resource — they are declared at `spec.xdcr.remoteClusters` on the `CouchbaseCluster`.

Field names in this skill come from the current resource reference. CRD schemas change between Operator releases, so check `kubectl explain couchbasecluster.spec` against your installed CRDs before committing a manifest.

## Related skills

- `couchbase-sizing` — node count, memory and disk arithmetic, before you write the CRD
- `couchbase-upgrade` — version paths and breaking changes, which the Operator does not decide for you
- `couchbase-observability` — metric names and what to alert on; the scrape mechanics for pods are here
- `couchbase-security-hardening` — the TLS and RBAC concepts behind the security fields
- `couchbase-backup-restore` — backup strategy, which the `CouchbaseBackup` resource only schedules
- `couchbase-admin-mcp` — the equivalent cluster administration surface off Kubernetes, which the Operator owns here instead
