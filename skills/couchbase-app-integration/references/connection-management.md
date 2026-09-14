# Connection management

How your application connects to Couchbase determines a lot — performance, resilience, security, operability. This reference covers connection strings, the Cluster object lifecycle, TLS setup, mTLS, and connection pooling behavior.

> **Verify SDK symbols against your pinned SDK version.** Class names, option objects and import paths differ across SDKs and across major versions of the same SDK. The Python and Java symbols below reflect the current documented surface; confirm against the versioned SDK docs before using them.

## Contents

- [The Cluster → Bucket → Collection model](#the-cluster--bucket--collection-model)
- [Connection strings](#connection-strings)
- [Authentication](#authentication)
- [TLS setup](#tls-setup)
- [Connection pooling](#connection-pooling)
- [Cluster object lifecycle](#cluster-object-lifecycle)
- [Failover behavior — what the SDK does automatically](#failover-behavior--what-the-sdk-does-automatically)
- [Network setups — public, private link, VPC peering](#network-setups--public-private-link-vpc-peering)
- [Connection string anti-patterns](#connection-string-anti-patterns)
- [Quick decision tree](#quick-decision-tree)

## The Cluster → Bucket → Collection model

All modern Couchbase SDKs follow the same hierarchy:

```
Cluster (one per application typically — owns connections, auth)
 └── Bucket (logical container, named at runtime)
      └── Scope (default: "_default")
           └── Collection (default: "_default")
                └── KV / Query operations happen here
```

```python
# Python example (Python SDK 4.x)
from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.options import ClusterOptions

cluster = Cluster.connect("couchbases://cb.example.com",
                          ClusterOptions(PasswordAuthenticator("user", "pass")))
bucket = cluster.bucket("my-bucket")
scope = bucket.scope("orders")
collection = scope.collection("active")
result = collection.upsert("order::42", {"total": 142.10})
```

**Key insight:** Cluster is the expensive object. Create it once at app startup; reuse it for the application's lifetime. Bucket, Scope, Collection are cheap handles — create as needed.

**Anti-pattern:** creating a new Cluster per request. This is the most common Couchbase performance bug. Connections take seconds to establish (TLS, auth, cluster map fetch); creating a new one per request adds that latency to every request.

## Connection strings

Format: `<scheme>://<host1>[,<host2>,<host3>][?option=value&...]`

| Scheme | Use |
|---|---|
| `couchbase://` | Non-TLS — not appropriate for production |
| `couchbases://` | TLS — the default and required scheme for Capella; recommended everywhere |
| `couchbase2://` | Cloud Native Gateway, for Couchbase deployed on Kubernetes / OpenShift via the Operator. Not a drop-in for every operation — check the SDK's Cloud Native Gateway page for which APIs it supports |

**Multiple hosts:** comma-separated. The SDK only needs ONE to be reachable; it fetches the full cluster map after connecting. Listing 2-3 is a good practice for first-connection resilience.

```
couchbases://cb-1.example.com,cb-2.example.com,cb-3.example.com
```

**Capella connection strings:** look like `couchbases://cb.<cluster-id>.cloud.couchbase.com`. Get it from `capella_cluster_get` or the Capella UI.

**Connection-string options are SDK-specific — do not assume one SDK's parameter names work in another.**

In the **Java SDK**, any client setting that has a system-property name may also be given as a connection-string parameter, with the `com.couchbase.env.` prefix dropped — so `timeout.kvTimeout`, `timeout.queryTimeout`, `io.numKvConnections`, `io.networkResolution` ([Java client settings](https://docs.couchbase.com/java-sdk/current/ref/client-settings.html)).

```
couchbases://cb-1.example.com?timeout.kvTimeout=5s&io.networkResolution=external
```

In the **Python SDK**, the documented route is the options objects rather than connection-string parameters — `ClusterOptions(...)` with `ClusterTimeoutOptions(kv_timeout=..., query_timeout=...)` ([Python client settings](https://docs.couchbase.com/python-sdk/current/ref/client-settings.html)). Prefer programmatic options everywhere; they are typed, discoverable, and portable across SDKs.

**Documented Java SDK defaults** (other SDKs are broadly aligned but confirm against your SDK's own settings page):

| Setting | Default |
|---|---|
| `kvTimeout` | 2.5s |
| `kvDurableTimeout` (durable writes) | 10s |
| `connectTimeout` | 10s |
| `queryTimeout` / `searchTimeout` / `analyticsTimeout` / `managementTimeout` | 75s |
| `idleHttpConnectionTimeout` | 1s |
| `numKvConnections` | 1 |
| `maxHttpConnections` | 12 |
| `configPollInterval` | 2.5s |

## Authentication

Modern SDKs use Password authentication (username + password) by default; some support certificate authentication (mTLS).

**Password auth:**

```java
// Java
Cluster cluster = Cluster.connect("couchbases://...",
    ClusterOptions.clusterOptions("username", "password"));
```

```python
# Python
auth = PasswordAuthenticator("username", "password")
cluster = Cluster("couchbases://...", ClusterOptions(authenticator=auth))
```

**Certificate auth (mTLS):** every SDK exposes a certificate authenticator, but the class name and its parameters differ per SDK — check your SDK's "Managing Connections" and authentication pages for the exact type and argument names before writing the code.

Password auth is the default; certificate auth is for highest-security environments where you don't want passwords in config. Couchbase Server 8.0 adds a **hybrid authentication mode**, allowing certificate *or* username/password credentials with mandatory mTLS ([What's New in 8.0](https://docs.couchbase.com/server/current/introduction/whats-new.html)).

## TLS setup

Production should always use TLS. The SDK needs to trust the cluster's certificate:

**Public CA-signed cert (e.g., Capella):** works out of the box. No client-side trust setup needed.

**Self-signed or internal-CA cert:** the SDK needs a path to the CA certificate to trust. In the Python SDK this is `ClusterOptions(..., trust_store_path="/path/to/ca-cert.pem")`; in the Java SDK it is `SecurityConfig.trustCertificate(Path)` on the cluster environment. Check your SDK's client-settings page for the exact option name.

```python
# Python SDK 4.x
options = ClusterOptions(
    PasswordAuthenticator("user", "pass"),
    trust_store_path="/path/to/ca-cert.pem",
)
cluster = Cluster.connect("couchbases://...", options)
```

**Specifying the CA cert** vs **disabling TLS verification:** never do the latter in production. Disabling verification means any man-in-the-middle can impersonate the cluster. If certs aren't working, fix the trust chain rather than disabling verification.

## Connection pooling

SDKs manage connection pooling internally. You don't typically need to configure this, but for high-throughput servers a few knobs help:

| Java setting | Documented default | When to tune |
|---|---|---|
| `numKvConnections` (KV sockets per node) | 1 | Increase for very high QPS workloads |
| `maxHttpConnections` (query/search/management) | 12 | Increase if running many concurrent queries |
| `idleHttpConnectionTimeout` | 1s | Match to your network's NAT/firewall idle timeout |

```java
// Java SDK 3.x — bump KV connections per node
Cluster cluster = Cluster.connect("couchbases://...",
    ClusterOptions.clusterOptions("username", "password")
        .environment(env -> env.ioConfig(io -> io.numKvConnections(2))));
```

Equivalent settings exist in the other SDKs under their own names; look them up rather than porting the Java spelling.

The default is fine for 95% of applications. Only tune if profiling shows connection contention.

## Cluster object lifecycle

**At startup:** create the Cluster, then call the SDK's wait-until-ready method (`cluster.wait_until_ready(timedelta(...))` in Python, `cluster.waitUntilReady(Duration)` in Java) to verify connectivity before serving traffic. Otherwise the first request pays the full bootstrap cost — and bootstrap can exceed the default KV timeout, so this is a correctness measure, not just a latency one.

**During runtime:** reuse the Cluster object. Bucket, Scope, Collection handles can be cached or re-obtained — both are cheap.

**At shutdown:** close the cluster cleanly — `cluster.close()` in the Python SDK, `cluster.disconnect()` in the Java SDK. Check your SDK's own spelling. Important for graceful shutdown; less important for crash recovery.

**Sample structure:**

```python
# Module-level singleton (Python SDK 4.x)
from datetime import timedelta
from typing import Optional

_cluster: Optional[Cluster] = None

def get_cluster() -> Cluster:
    global _cluster
    if _cluster is None:
        _cluster = Cluster.connect(
            CONN_STR,                                   # from env / secrets manager
            ClusterOptions(PasswordAuthenticator(USER, PASSWORD)),
        )
        _cluster.wait_until_ready(timedelta(seconds=10))
    return _cluster

def shutdown() -> None:
    if _cluster:
        _cluster.close()
```

For DI-based frameworks (Spring, ASP.NET Core), register Cluster as a singleton.

## Failover behavior — what the SDK does automatically

When a node fails:

1. SDK detects it via heartbeat / failed request
2. Retries the failed request against another node hosting the data (within the SDK's retry budget — typically the operation's timeout)
3. Caller sees either success (if retry worked) or timeout/failure (if cluster genuinely can't serve)

Cluster topology changes (failover, rebalance, node add) are propagated to the SDK via the config endpoint. The SDK updates its routing tables transparently. **You don't write code to handle node failures** — the SDK handles it. Your code only sees the outcome.

## Network setups — public, private link, VPC peering

**Public access** (default Capella): `couchbases://cb.<id>.cloud.couchbase.com`. Allowed CIDRs in Capella must include your app's egress IP.

**Private endpoint / private link:** the cluster advertises separate internal and external addresses, and the SDK's *network resolution* setting decides which to use. The default is `auto`, which is usually correct; force it only when auto-detection picks wrong. In the Java SDK the setting is `io.networkResolution` (`auto` / `default` / `external`); other SDKs expose an equivalently-named option — look it up for yours.

**VPC peering (cloud):** treat as a private network — same connection string format as public but lower latency and no internet egress cost.

For all setups: the network path matters more than the connection string. A misconfigured firewall causes the same symptom as a wrong connection string (connection refused). Verify network reachability before debugging client config.

## Connection string anti-patterns

- **Hardcoded credentials in connection strings:** put credentials in env vars / secrets manager, not in code
- **Passing the cluster object across processes** (forking after connection): the connections aren't shared across the fork; the child gets broken sockets. Connect AFTER fork
- **One Cluster per database operation:** see "Cluster object lifecycle" above — Cluster is meant to live for the app's lifetime
- **Hardcoding bucket / scope / collection in connection string:** the connection string is the cluster address; specify bucket/scope/collection separately

## Quick decision tree

- **Cluster object — when to create?** Once at app startup; reuse for app lifetime
- **TLS — when to use?** Always in production; mandatory for Capella (always use `couchbases://`)
- **Self-signed cert?** Pass `cert_path` to the cluster options; don't disable TLS verification
- **Capella?** Use `couchbases://`; take the connection string from the Capella UI or Capella Management API; ensure the allowed CIDR list includes your app's egress IP
- **Kubernetes / OpenShift with the Operator?** `couchbase2://` (Cloud Native Gateway) may apply — check your SDK's Cloud Native Gateway support page first
- **Auth method?** Password (default); mTLS if your security posture requires it
- **Connection pooling?** SDK handles automatically; only tune for very high QPS
- **Node failed?** SDK handles routing; your code does nothing special
