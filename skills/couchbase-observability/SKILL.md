---
name: couchbase-observability
description: "Monitor and alert on Couchbase Server clusters in production. Use whenever the user asks about Couchbase metrics and metric names, the Prometheus metrics endpoint, scraping Couchbase with Prometheus, Grafana dashboards, alert thresholds, memory watermarks and ejection, background fetches and residency, disk queue and fragmentation, DCP or XDCR backlog, query latency and queued requests, index memory and scan efficiency, Search indexing backlog, node health from /pools/default, log file locations and log aggregation, CMOS, or 'how do I know if my Couchbase cluster is healthy'. Covers Couchbase Server 7.x and 8.0, including the metric renames and deprecated statistics endpoints introduced in 8.0. Distinct from couchbase-security-hardening, which covers audit log configuration and shipping. Use proactively when setting up an observability stack for a new production deployment, defining SLOs, or preparing incident response."
license: Apache-2.0
---

# Couchbase Observability

Monitoring and alerting for Couchbase Server in production — metric names, the Prometheus integration, dashboards, log aggregation, and how to arrive at thresholds that are defensible.

Distinct from `couchbase-security-hardening`, which covers audit event configuration and shipping audit logs to a SIEM. Operational logs and audit logs are different pipelines with different retention.

## Two things to get right before anything else

**Metric names are not stable across releases, and three naming systems are in circulation** — the Prometheus exposition names, the Web Console labels, and the legacy REST statistics field names. Everything in this skill uses the Prometheus exposition names. Verify any name against the metrics reference for the release you are monitoring before it goes into an alert rule; a rule with a wrong name matches nothing and fails silently.

**Couchbase publishes almost no alert thresholds.** Numbers presented as Couchbase-recommended thresholds are, with very few exceptions, invented. `references/alert-thresholds.md` gives you a derivation method and is explicit about which numbers are documented defaults and which are operational judgement.

## What 8.0 changed

If the cluster is on 8.0, or is being upgraded to it, these will break existing monitoring:

- **"Cache Miss Ratio" was renamed "Get Miss Ratio."** It measures gets that fail because the key does not exist, not RAM cache misses — and has done since 7.6.2. It never meant what most dashboards claim it means.
- **`kv_vb_ht_memory_bytes` is deprecated in favour of `kv_vb_ht_memory_overhead`.** Both exist in 8.0; the old one will be removed.
- **`kv_ep_mem_high_wat_percent_ratio` and `kv_ep_mem_low_wat_percent_ratio` changed scale**, from 0–0.01 to 0–1. Thresholds tuned on 7.x will not fire.
- **The per-bucket statistics REST endpoints are deprecated** in favour of `GET /pools/default/stats/range/...` and `POST /pools/default/stats/range`.
- **`audit.log` is now a symlink** to the file currently being written, which changes how a log shipper must follow it.
- **Memcached buckets are removed**, so any bucket-type dimension loses that series.

Details and the current names are in `references/key-metrics.md`.

## When this skill applies

- "How do I monitor Couchbase?" / "How do I know if a node is healthy?"
- "How do I scrape Couchbase with Prometheus? What role does the scrape user need?"
- "What metrics matter, and what does this metric actually mean?"
- "What should I set this alert threshold to?"
- "Why did my dashboard stop working after the upgrade?"
- "How do I aggregate Couchbase logs? Where are the log files?"
- "Should I use the Couchbase exporter or the built-in endpoint?"

## Pick the right reference

| Question | Read |
|---|---|
| Current metric names, what each one means, the 7.6/8.0 renames, node health fields | `references/key-metrics.md` |
| Metrics endpoint and port, the `external_stats_reader` scrape account, service discovery, scrape config, recording rules, dashboard structure, the exporter, CMOS | `references/prometheus-grafana.md` |
| How to derive thresholds, what to alert on and why, severity model, alert fatigue | `references/alert-thresholds.md` |
| Log file locations and names, rotation behaviour, shipper design, log-based alerting, `cbcollect_info` | `references/log-aggregation.md` |

## Three core principles

**Alert on symptoms, not causes.** Rejected writes are a symptom; compaction falling behind is a cause. Alerting on symptoms produces fewer false positives and misses fewer real incidents, because there are many causes for each symptom and you cannot enumerate them in advance.

**Baseline before you threshold.** Couchbase metrics vary enormously by workload. A background-fetch rate that signals an emergency on a session store is the designed steady state on an archive. Measure for a full business cycle, then set thresholds from your own percentiles.

**Every node matters.** Couchbase is a distributed system. One node under memory pressure, one node with a full disk, or one node behind on replication degrades the whole cluster. Aggregate for dashboards; alert per node on resource pressure. A cluster average will hide exactly the node that is about to fail.

## The monitoring surface

| Task | Surface |
|---|---|
| All current metrics, per node, Prometheus format | `GET /metrics` on 18091 (TLS) or 8091 |
| Discover the cluster's scrape targets | `GET /prometheus_sd_config` |
| Node health, membership, storage totals, rebalance status, alerts | `GET /pools/default` |
| Historical statistics for a metric | `GET /pools/default/stats/range/<metric>/<function>`; `POST` for several at once |
| Cluster event history | The system events REST API |
| Logs | Files under `/opt/couchbase/var/lib/couchbase/logs` on each node |
| Support bundle | `cbcollect_info`, run per node |

The scrape account needs exactly one role: `external_stats_reader`. It is cluster-wide, carries no data access, and exists so that a monitoring identity never needs `cluster_admin`.

The official Couchbase MCP server (`couchbase/mcp-server-couchbase`, docs at https://mcp-server.couchbase.com/) is read-only by default (`CB_MCP_READ_ONLY_MODE=true`) and offers cluster health and query-performance tools — useful for ad-hoc investigation, not a substitute for a metrics pipeline.

## Related skills

- `couchbase-security-hardening` — audit logging, and the `external_stats_reader` role in the wider RBAC picture
- `couchbase-kubernetes` — scraping Couchbase pods under the Kubernetes Operator
- `couchbase-xdcr` — interpreting `xdcr_changes_left_total` and XDCR failure modes
- `couchbase-eventing` — Eventing function statistics
- `couchbase-capella` — Capella's built-in monitoring integration, in place of self-managed scraping
- `couchbase-performance-tuning` — what to change once a metric shows the cluster is right-sized but slow
