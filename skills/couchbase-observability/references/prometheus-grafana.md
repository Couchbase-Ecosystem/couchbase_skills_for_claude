# Prometheus and Grafana

## Contents

- [The metrics endpoint](#the-metrics-endpoint)
- [The scrape account](#the-scrape-account)
- [Service discovery](#service-discovery)
- [Static scrape configuration](#static-scrape-configuration)
- [Recording rules](#recording-rules)
- [Dashboard structure](#dashboard-structure)
- [The Couchbase Prometheus Exporter](#the-couchbase-prometheus-exporter)
- [CMOS](#cmos)

## The metrics endpoint

**Couchbase Server 7.0+** exposes a Prometheus-compatible endpoint natively — no exporter, no sidecar, no agent:

```
https://<node>:18091/metrics      # TLS
http://<node>:8091/metrics        # plaintext
```

That is the management port, and the metrics it returns are for **that node**. Scrape every node; do not scrape one node and assume it speaks for the cluster.

If the cluster is at encryption level `strict`, only the 18091 form answers.

## The scrape account

Create a dedicated local user holding exactly one role:

```
external_stats_reader
```

That is the documented role for reading metrics and calling the discovery API. It is cluster-wide and carries no data access.

**Do not give a scrape account `cluster_admin`.** It is a common piece of folklore and it is wrong — `external_stats_reader` exists precisely so that a monitoring identity does not need an administrative role. A `cluster_admin` scrape credential sitting in a Prometheus config file is a privilege-escalation path to full cluster management.

```bash
couchbase-cli user-manage -c <host> -u <admin> -p <password> \
  --set --auth-domain local \
  --rbac-username prometheus --rbac-password '<generated>' \
  --roles external_stats_reader --rbac-name 'Prometheus scrape account'
```

## Service discovery

Couchbase exposes an HTTP service-discovery endpoint, `/prometheus_sd_config`, which returns the cluster's current node list in the format Prometheus consumes. Use it instead of a static target list so that adding or removing a node does not require a Prometheus config change:

```yaml
scrape_configs:
  - job_name: couchbase
    scheme: https
    basic_auth:
      username: prometheus
      password: <password>
    tls_config:
      ca_file: /etc/prometheus/couchbase-ca.pem
    http_sd_configs:
      - url: https://<node>:18091/prometheus_sd_config
        basic_auth:
          username: prometheus
          password: <password>
        tls_config:
          ca_file: /etc/prometheus/couchbase-ca.pem
```

Point the discovery URL at more than one node, or at a load-balanced address, so discovery itself is not a single point of failure.

## Static scrape configuration

Where service discovery is not available:

```yaml
scrape_configs:
  - job_name: couchbase
    scheme: https
    metrics_path: /metrics
    basic_auth:
      username: prometheus
      password: <password>
    tls_config:
      ca_file: /etc/prometheus/couchbase-ca.pem
      insecure_skip_verify: false
    static_configs:
      - targets:
          - "node1.example.com:18091"
          - "node2.example.com:18091"
          - "node3.example.com:18091"
        labels:
          cluster: prod
```

Keep `insecure_skip_verify: false`. A monitoring pipeline that skips verification is a monitoring pipeline that can be fed by anyone on the network.

Couchbase's exposition is wide. If cardinality is a problem, drop series you do not use with `metric_relabel_configs` — but measure first rather than dropping families by guesswork.

## Recording rules

Pre-compute what dashboards query repeatedly. Note that the expressions below are **derivations you are choosing to define**, not Couchbase-defined statistics:

```yaml
groups:
  - name: couchbase
    interval: 60s
    rules:
      # Fraction of get operations served from disk rather than RAM.
      # Couchbase exposes no such metric; this is a derived approximation.
      - record: couchbase:bucket:disk_fetch_fraction
        expr: |
          rate(kv_ep_bg_fetched[5m])
          / clamp_min(rate(kv_ops{op="get"}[5m]), 1)

      - record: couchbase:bucket:mem_vs_high_wat
        expr: kv_mem_used_bytes / clamp_min(kv_ep_mem_high_wat, 1)

      - record: couchbase:index:memory_utilization
        expr: index_memory_used_total / clamp_min(index_memory_quota, 1)

      - record: couchbase:xdcr:changes_left_max
        expr: max(xdcr_changes_left_total) by (cluster, pipeline)
```

Check the label names on `kv_ops` against your own cluster's exposition before relying on `op="get"`; label sets have changed across releases.

## Dashboard structure

Four sections, in this order, works well:

**1. Cluster overview.** Node count by health state, total operations per second, worst-node memory position, worst-node disk utilisation, connection count. Everything here should be a single number that is either fine or not.

**2. Per-node resources.** Memory, CPU and disk per node, as separate series rather than an average. Couchbase is a distributed system and an average hides the one node that is about to fall over — this is the single most common dashboard design mistake.

**3. Bucket performance.** Operations by type, background fetch rate, residency ratio, disk queue fill against drain, per collection where the bucket is shared.

**4. Service health.** Query latency percentiles and queued requests; index memory utilisation and scan efficiency; Search indexing backlog; XDCR backlog per pipeline.

Grafana has published Couchbase dashboards available for import; treat any of them as a starting point and verify every panel's metric name against the reference for your release, because dashboards age badly across the 7.6 and 8.0 metric changes described in `key-metrics.md`.

## The Couchbase Prometheus Exporter

Couchbase publishes an exporter at `couchbase/couchbase-exporter`. Two things to know before reaching for it:

- Its support statement scopes it to Couchbase Enterprise subscribers **in conjunction with the Couchbase Kubernetes (Autonomous) Operator**.
- Within the operator, the exporter sidecar is the **legacy** path and is documented as deprecated; native Couchbase Server metrics are the recommended approach for Server 7.0+.

So for a self-managed cluster on 7.0 or later, scrape `/metrics` directly. Do not add the exporter on the assumption that it returns more than the native endpoint — that claim is not supported by the documentation, and the operator's guidance points the other way.

## CMOS

The Couchbase Monitoring and Observability Stack (CMOS) packages Prometheus, Grafana and a cluster monitor with Couchbase-authored default configuration. It is a useful reference for what good default dashboards and rules look like.

**CMOS is a Developer Preview.** The documentation states it may not be functionally complete and is not intended for production use, and it carries no official support. Mine it for configuration; do not put it in the path of a production on-call rotation.
