---
name: couchbase-performance-tuning
description: "Diagnose and tune cluster-level performance problems in Couchbase. Use whenever the user asks about slow KV operations, high latency, low throughput, DCP backpressure, connection limits, thread pool tuning, compaction impact on performance, autocompaction settings, KV engine tuning, vBucket distribution, rebalance performance, disk I/O bottlenecks, CPU saturation on Couchbase nodes, network throughput limits, or 'my cluster is healthy but slow.' Distinct from couchbase-sqlpp-tuning (SQL++ query tuning — index design and EXPLAIN plans), couchbase-observability (what metrics to watch), and couchbase-sizing (how much capacity to provision). This skill covers the operational tuning layer: what to change when the cluster is right-sized but still not performing."
license: Apache-2.0
---

# Couchbase Performance Tuning

A skill for diagnosing and fixing performance problems at the cluster level — KV latency, throughput limits, disk I/O, compaction, connection saturation, and thread pool configuration.

Distinct from:
- `couchbase-sqlpp-tuning` — SQL++ query tuning (index design, EXPLAIN plans, anti-patterns)
- `couchbase-observability` — what metrics to monitor and alert thresholds
- `couchbase-sizing` — how much capacity to provision in the first place

If the question is "my queries are slow," go to `couchbase-sqlpp-tuning`. If the question is "my cluster is right-sized but everything is slow," this is the right skill.

## When this skill applies

- "KV get/set latency is higher than expected"
- "Throughput isn't reaching the hardware's capability"
- "Compaction is killing performance"
- "We're hitting connection limits"
- "Rebalance is taking too long"
- "High CPU on Couchbase nodes but no obvious cause"
- "Disk I/O is spiking unpredictably"
- "DCP consumers are falling behind"

## Pick the right reference

| Question | Read |
|---|---|
| "KV latency / throughput — diagnosis and tuning" | `references/kv-tuning.md` |
| "Compaction — autocompaction settings, impact, tuning" | `references/compaction.md` |
| "Connection limits, thread pools, OS-level tuning" | `references/system-tuning.md` |

## The diagnosis sequence

Before tuning anything, locate the actual bottleneck:

1. **Is it memory?** Check bucket memory use against the watermarks. The documented defaults are a low watermark of 75% and a high watermark of 85% — once use crosses the high watermark, ejection starts and reads of ejected documents go to disk. Fix: add RAM, add nodes, or reduce the working set.

2. **Is it disk I/O?** Check `ep_bg_fetched` (reads going to disk) and `ep_diskqueue_drain` vs `ep_diskqueue_fill`. Fix: faster storage, reduce write rate, or move the bucket to Magma (Enterprise Edition, 7.1+) if the working set does not fit in memory.

3. **Is it CPU?** Check per-node CPU utilization. Which service is consuming it? Query and Index are CPU-heavy; KV should be low-CPU unless you're near capacity. Fix: dedicated nodes per service, or add nodes.

4. **Is it network?** Check `bytes_sent` and `bytes_received` per node against the node's NIC capacity. Fix: higher-bandwidth instances, or reduce replication/XDCR traffic.

5. **Is it compaction?** Check if high disk I/O correlates with compaction windows. Fix: adjust compaction schedule, thresholds, or parallelism.

6. **Is it connection count?** Check `curr_connections` per node against the configured maximum and the documented 60,000 concurrent key-value connections per Data node. Fix: right-size SDK connection pools first; raise cluster connection settings and OS file descriptors only if the pools are already correct.

Only tune after locating the bottleneck. Tuning the wrong thing wastes time and can make things worse.

## Before quoting any number

Couchbase publishes defaults and hard limits; it does not publish achievable latency or throughput figures, because those depend on document size, durability level, residency, storage engine, instance type and network. Where this skill gives a number it is a documented default or limit with a source. Everything else is a measurement you take on your own cluster — establish a baseline before a change and compare against it after.

Version and edition gating matters when reading any tuning advice: Magma is Enterprise Edition only (7.1+), the 128 vBucket configuration and Magma-by-default are 8.0+ EE only, and several metrics were renamed in 8.0 (for example "Cache Miss Ratio" became "Get Miss Ratio").

## Related skills

- `couchbase-sqlpp-tuning` — query-level performance (EXPLAIN, indexes, CBO)
- `couchbase-observability` — key metrics definitions and alert thresholds
- `couchbase-magma` — Magma storage engine characteristics that affect disk I/O and compaction behavior
- `couchbase-upgrade` — 8.0 metric renames and removed interfaces that affect monitoring
- `couchbase-sizing` — if tuning can't solve the problem, the next step is adding capacity
- `couchbase-mcp` — gathering the diagnostics and query statistics these decisions rest on, over MCP
- `couchbase-admin-mcp` — the `admin_stats_*`, `admin_cluster_memory_set` and `admin_rebalance_progress` tools the system-level changes here go through
