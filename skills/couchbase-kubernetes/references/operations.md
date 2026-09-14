# Operations

## Contents

- [Rolling upgrades](#rolling-upgrades)
- [Scaling](#scaling)
- [Online volume expansion](#online-volume-expansion)
- [Prometheus monitoring](#prometheus-monitoring)
- [Logs](#logs)
- [Hibernation](#hibernation)
- [Troubleshooting](#troubleshooting)

## Rolling upgrades

Upgrading Couchbase Server means changing `spec.image`. The Operator detects the change and carries out the upgrade according to `spec.upgrade` (see `cluster-crd.md`).

**Before you touch `spec.image`:** confirm that your Operator release supports the target Couchbase Server version. Operator 2.9.x supports Couchbase Server Enterprise Edition 7.2 through 8.0; Server 8.0 needs at least Operator 2.8.1. Check the current platform support page rather than trusting that sentence — it ages. Upgrading the Operator first, then Couchbase Server, is the usual order.

**Before upgrading to Couchbase Server 8.0 specifically:** remove every Memcached bucket. They were removed in 8.0, and the cluster upgrade fails if any are present. Ephemeral buckets are the replacement.

```bash
kubectl patch couchbasecluster couchbase-prod \
  --namespace couchbase-prod --type merge \
  -p '{"spec":{"image":"couchbase/server:<target-EE-tag>"}}'
```

Under the default `SwapRebalance` process, the Operator creates a new pod, rebalances data onto it, and deletes the old one, repeating per batch. **This needs spare capacity in the Kubernetes cluster** — enough to schedule the additional pods and provision their volumes. An upgrade that stalls immediately is usually an unschedulable new pod, not an Operator fault.

Watch it:

```bash
kubectl describe couchbasecluster couchbase-prod -n couchbase-prod
kubectl get events -n couchbase-prod --sort-by='.lastTimestamp'
kubectl logs -n <operator-namespace> deployment/couchbase-operator -f
```

The resource's `status` conditions are the authoritative view of where the Operator thinks it is.

## Scaling

Change `spec.servers[].size`:

```bash
kubectl patch couchbasecluster couchbase-prod \
  --namespace couchbase-prod --type json \
  -p '[{"op":"replace","path":"/spec/servers/0/size","value":5}]'
```

The Operator adds the pods, joins them, and rebalances. Scaling in gracefully removes the excess pods and rebalances data off them first.

Two things to hold in mind:

- **Every scaling operation is a rebalance**, which moves data across the network and takes as long as the data volume dictates. It is not a fast operation, and it should not be triggered casually or automatically without a stabilisation period.
- **Scaling a data class interacts with server groups.** If you have three zones and scale from 3 to 4 data pods, the distribution is no longer even. Prefer scaling in multiples of the server group count.

## Online volume expansion

Volumes can be grown in place, and only grown — shrinking is not possible at the Kubernetes level, let alone here.

Two prerequisites:

1. `spec.enableOnlineVolumeExpansion: true` on the `CouchbaseCluster`.
2. A storage class with `allowVolumeExpansion: true`.

Then raise the size in the relevant volume claim template:

```bash
kubectl patch couchbasecluster couchbase-prod \
  --namespace couchbase-prod --type json \
  -p '[{"op":"replace","path":"/spec/volumeClaimTemplates/0/spec/resources/requests/storage","value":"800Gi"}]'
```

The Operator expands the volumes sequentially across affected pods and emits events as it goes. The cluster stays online.

**The expansion applies to every service referencing that claim template**, not to selected pods — so if data and index share a template, both grow. Separate templates per service if you want to grow them independently.

## Prometheus monitoring

For **Couchbase Server 7.0 and later, use the native metrics endpoint.** Couchbase Server exposes a Prometheus-compatible endpoint on every pod with no exporter, no sidecar and no configuration in the `CouchbaseCluster` resource: port 8091, or 18091 with TLS enabled, at `/metrics`.

Create a Service that selects the Couchbase pods, then a `ServiceMonitor` (or `PodMonitor`) pointing at the metrics port, with credentials for a Couchbase user holding the `external_stats_reader` role — see `couchbase-observability/references/prometheus-grafana.md` for why that role and not `cluster_admin`.

The older path configured an exporter sidecar:

```yaml
spec:
  monitoring:
    prometheus:
      enabled: true
      image: couchbase/exporter:<tag>
      authorizationSecret: <secret>
      refreshRate: 60
```

**This exporter sidecar approach is deprecated and is documented as due for removal in a future release.** It exposes metrics on a separate port. Do not build new deployments on it, and migrate existing ones to the native endpoint.

## Logs

Couchbase writes its logs inside the pod, under the Couchbase log directory on the mounted volume — not to stdout. `kubectl logs` therefore shows you very little.

```bash
# The real logs
kubectl exec -n couchbase-prod <pod> -- \
  tail -100 /opt/couchbase/var/lib/couchbase/logs/error.log

# Container stdout — startup only, mostly
kubectl logs -n couchbase-prod <pod> --tail=100

# Previous container instance after a crash
kubectl logs -n couchbase-prod <pod> --previous
```

For real aggregation, run a log collector that can read the Couchbase log directory from each pod — as a sidecar with the logs volume mounted, or as a DaemonSet where the node layout permits. Configuration design, file names and rotation behaviour are in `couchbase-observability/references/log-aggregation.md`, including the 8.0 change that makes `audit.log` a symlink.

For a support case, run `cbcollect_info` inside the pod and copy the bundle out with `kubectl cp`.

## Hibernation

```bash
kubectl patch couchbasecluster couchbase-staging \
  --namespace couchbase-staging --type merge \
  -p '{"spec":{"hibernate":true}}'
```

Setting `hibernate: false` brings it back. Pods are scaled to zero; persistent volumes are retained, so data survives.

This is for non-production environments that do not need to run continuously. Do not hibernate anything that a replica, a backup schedule or an XDCR pipeline depends on — a hibernated source cluster is a stalled replication.

## Troubleshooting

**Cluster stuck mid-operation.** Read the resource conditions and events first; the Operator explains itself there better than in its own log.
```bash
kubectl describe couchbasecluster <name> -n <namespace>
```

**Pod `Pending`.** Almost always scheduling or storage. Check in this order: is the PVC bound; does a node carry the `topology.kubernetes.io/zone` label the server group names; is there room for the pod's resource request; does `antiAffinity: true` mean there are not enough distinct nodes.
```bash
kubectl get pvc -n <namespace>
kubectl describe pod <pod> -n <namespace>
kubectl get nodes --show-labels
```

**Pod starts then cannot write.** Missing `spec.securityContext.fsGroup` on non-OpenShift Kubernetes. It reads as a storage failure but is a permissions failure.

**Pod in `CrashLoopBackOff`.** `kubectl logs --previous`, then the Couchbase logs on the volume if the pod stays up long enough to exec into.

**Rebalance not progressing.** Check the Operator log and the rebalance report in the `rebalance/` subdirectory of the log directory on a node.

**A change you made reverted itself.** You changed it through the Web Console or REST API on a cluster the Operator manages. Make the change in the custom resource.

**Admission webhook rejects a resource.** Read the message — it is usually a genuine schema violation. If it reports the webhook is unreachable, the admission controller deployment is unhealthy or was never installed; see `installation.md`.
