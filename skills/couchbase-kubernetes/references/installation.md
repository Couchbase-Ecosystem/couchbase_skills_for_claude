# Installing the Operator

## Contents

- [Prerequisites](#prerequisites)
- [What gets installed](#what-gets-installed)
- [Install with the cao CLI](#install-with-the-cao-cli)
- [Install with Helm](#install-with-helm)
- [The admission controller is cluster-scoped](#the-admission-controller-is-cluster-scoped)
- [Namespaces](#namespaces)
- [Admin credentials secret](#admin-credentials-secret)
- [TLS secrets](#tls-secrets)
- [Storage class requirements](#storage-class-requirements)
- [Filesystem group](#filesystem-group)

## Prerequisites

- A Kubernetes or OpenShift cluster within the supported version range for the Operator release you are installing — check the platform support page, do not assume
- `kubectl` (or `oc`) configured against it
- Helm 3, if installing by chart
- A dynamic volume provisioner; persistent volumes are mandatory for production
- A Couchbase Server **Enterprise Edition** entitlement

## What gets installed

The Operator is three pieces, and knowing which is which makes the failure modes legible:

1. **Custom Resource Definitions** — cluster-scoped, installed once per Kubernetes cluster.
2. **Dynamic Admission Controller (DAC)** — cluster-scoped, deployed **once per Kubernetes cluster**. It validates custom resources before the API server accepts them.
3. **Operator** — deployed **per namespace**. This is the controller that reconciles clusters.

Both the DAC and the Operator must be fully ready before you create a `CouchbaseCluster`.

## Install with the `cao` CLI

The Operator package ships a `cao` command-line tool that is the most direct route:

```bash
kubectl apply -f crd.yaml      # the CRDs, once per Kubernetes cluster
bin/cao create admission       # the cluster-scoped admission controller
bin/cao create operator        # the per-namespace operator
```

Confirm both deployments are available before continuing:

```bash
kubectl rollout status deployment/couchbase-operator-admission
kubectl rollout status deployment/couchbase-operator -n <namespace>
```

## Install with Helm

```bash
helm repo add couchbase https://couchbase-partners.github.io/helm-charts/
helm repo update
```

The chart is `couchbase/couchbase-operator`, and it can install the Operator, the admission controller, a Couchbase cluster and Sync Gateway together. For production you almost always want the Operator and admission controller only, then a cluster resource you manage yourself:

```bash
helm install <release> couchbase/couchbase-operator \
  --namespace <namespace> --create-namespace \
  --set install.couchbaseCluster=false \
  --set install.syncGateway=false
```

The chart's `install` block controls which components are deployed:

```yaml
install:
  couchbaseOperator: true
  admissionController: true
  couchbaseCluster: false
  syncGateway: false
```

Everything else is in the chart's `values.yaml`; supply overrides with `--values` or `--set`.

## The admission controller is cluster-scoped

**Deploy the admission controller exactly once per Kubernetes cluster.** A second release that also installs it will fail, because the webhook configuration is a cluster-scoped object that already exists.

So for the second and subsequent releases in a cluster:

```bash
helm install <release> couchbase/couchbase-operator \
  --set install.admissionController=false ...
```

This is the most common Helm failure people hit on their second environment, and the error message does not make the cause obvious.

## Namespaces

The Operator watches one namespace by default. Use a namespace per environment, with its own Operator deployment, so that a mistake in staging cannot reconcile production. The Operator can be configured to watch multiple namespaces where that trade-off is acceptable; see the operator deployment settings reference for the exact configuration in your release.

## Admin credentials secret

The Operator needs Couchbase administrator credentials. Create the secret before the cluster:

```bash
kubectl create secret generic couchbase-operator-credentials \
  --namespace <namespace> \
  --from-literal=username=Administrator \
  --from-file=password=/dev/stdin <<< "$(generate-a-strong-password)"
```

Reference it from `spec.security.adminSecret`. Note the quoting: passing a password through `--from-literal` in a command that your shell also expands is a reliable way to store a literal `$(...)` as the password. Generate the value first, or read it from a file.

In practice this secret should come from your secrets-management integration rather than from `kubectl create secret`, so that it is not sitting in shell history and in etcd unmanaged.

## TLS secrets

TLS certificates are supplied as Kubernetes secrets and referenced from `spec.networking.tls`. The Operator supports both static secrets you manage and integration with a certificate manager for automated issuance and rotation.

Automated rotation is worth the setup effort here: an expired node certificate takes the whole cluster's TLS surface down at once, and doing rotation by hand across every node is exactly the kind of task that gets deferred.

Check the Operator's TLS how-to for the secret key names expected by your release — they have changed across Operator versions, and a secret with the right content under the wrong keys fails in a confusing way.

## Storage class requirements

For production data nodes, the storage class needs:

- **`allowVolumeExpansion: true`** — required for online volume expansion. You cannot add this capability to volumes after the fact in a useful way, so set it from the start.
- **`volumeBindingMode: WaitForFirstConsumer`** — late binding, so the volume is provisioned in the same zone as the pod that will use it. Without it, in a multi-zone cluster, you will eventually get a volume in one zone and a pod that can only be scheduled in another, and the pod stays `Pending`. Some storage providers work transparently across zones; confirm with your Kubernetes vendor rather than assuming.
- **Durable block storage** with performance appropriate to the service. Data and Index want fast storage; logs do not.

**Reclaim policy:** the Couchbase documentation states that the reclaim policy is largely irrelevant here, because the Operator keeps volumes alive through PersistentVolumeClaims rather than relying on the storage class, and it **recommends `Delete`**. The reasoning is that Operator volume names derive from the cluster name, so retained volumes from a deleted cluster collide with the volumes of a cluster recreated under the same name.

This is worth stating explicitly because the instinct — and a lot of general Kubernetes advice — says `Retain` for anything holding data. For Operator-managed Couchbase volumes, follow the Couchbase guidance. Data durability comes from replicas and from backups, not from orphaned PVs.

Which provisioner and which volume type to use is a decision for your platform team and your cloud or storage vendor; this skill deliberately does not recommend one.

## Filesystem group

Couchbase pods do not run as root, so the persistent volume must be mounted with a filesystem group the Couchbase user belongs to. Set it explicitly:

```yaml
spec:
  securityContext:
    fsGroup: 1000
```

On Kubernetes any non-zero value works. On Red Hat OpenShift you do not need to populate this field — OpenShift assigns it.

Omitting `fsGroup` on plain Kubernetes produces a pod that starts and then fails to write to its volume, which reads as a storage fault rather than a permissions one.
