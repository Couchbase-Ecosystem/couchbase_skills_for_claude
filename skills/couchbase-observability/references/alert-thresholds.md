# Alert thresholds

## Contents

- [Read this first](#read-this-first)
- [The only numbers Couchbase documents](#the-only-numbers-couchbase-documents)
- [How to derive your own thresholds](#how-to-derive-your-own-thresholds)
- [What to alert on, and what the signal means](#what-to-alert-on-and-what-the-signal-means)
- [Severity model](#severity-model)
- [Alert fatigue prevention](#alert-fatigue-prevention)

## Read this first

Couchbase does not publish recommended alert thresholds. Any table of the form "warn at 80%, page at 90%" that claims to be a Couchbase default is invented, and this file used to contain one.

Two thresholds below are genuine Couchbase defaults because they are configuration values with documented defaults. Everything else in this file is either a **method** for deriving a number from your own cluster, or a statement about what a metric means. Where a number is an operational judgement call, it is labelled as such — do not let it graduate into a runbook as a documented default.

This is not evasion. Couchbase thresholds genuinely do not transfer between deployments: a background-fetch rate that means disaster on a session store is the designed steady state on an archive bucket, and a disk utilisation that is comfortable with aggressive auto-compaction is dangerous without it.

## The only numbers Couchbase documents

| Value | Default | What it is |
|---|---|---|
| Memory high watermark | 85% of bucket quota | The point at which the data service starts ejecting documents from RAM. Configurable per bucket |
| Memory low watermark | 75% of bucket quota | The point at which ejection stops. Configurable per bucket |

These are the *cluster's own* behavioural thresholds, not alert thresholds. Crossing the high watermark is Couchbase working as designed — it is not, by itself, an incident. Alerting on the watermark crossing is the classic Couchbase false-positive generator.

## How to derive your own thresholds

1. **Instrument before you alert.** Collect for at least one full business cycle — a week for most workloads, a month if you have month-end batch load. You cannot threshold what you have not measured.
2. **Take the percentile, not the peak.** Use something like the 95th percentile of the metric over the baseline window as "normal," so a single spike does not define your headroom.
3. **Set the page threshold where you still have time to act.** Work backwards: how long from this level to user impact, and how long does remediation take? The page must fire with enough margin to complete the fix. For disk that means accounting for compaction's temporary space needs; for memory it means time to add a node and rebalance.
4. **Set the warning one intervention-lead-time earlier.** A warning that fires five minutes before the page is a duplicate alert.
5. **Require duration.** Almost every Couchbase metric spikes momentarily under normal operation. Require the breach to persist for a few evaluation intervals before paging.
6. **Re-derive after every capacity change, version upgrade or workload shift.** Note in particular the 7.6/8.0 metric changes in `key-metrics.md` — the watermark ratio metrics changed scale in 8.0, so thresholds set on 7.x will not mean the same thing after upgrade.

## What to alert on, and what the signal means

Alert on symptoms the user would feel; investigate causes during the incident.

**Memory and write rejection**

- `kv_ep_tmp_oom_errors` — any sustained non-zero rate means clients are being told to back off. This is a real symptom, and it is one of the few metrics where "greater than zero, sustained" is a defensible condition without baselining.
- `kv_ep_oom_errors` — writes rejected outright. Treat as an incident on any occurrence.
- `kv_mem_used_bytes` against `kv_ep_mem_high_wat` — track it, and set the threshold from your own ejection tolerance. Do not alert simply on crossing the watermark.

**Working set no longer fitting**

- `kv_ep_bg_fetched` rising while document count is flat. Threshold against *your* baseline rate; there is no meaningful absolute number.
- `kv_vb_perc_mem_resident_ratio` falling. Same — the acceptable floor is a property of the workload.

**Disk**

- Node disk utilisation, from your host metrics rather than from Couchbase. The margin must cover compaction's working space, which can be substantial; size the threshold from observed compaction behaviour on this cluster.
- `kv_ep_diskqueue_fill` sustained above `kv_ep_diskqueue_drain`. The condition is the inequality, not a queue-depth number.
- The gap between `kv_ep_db_data_size_bytes` and `kv_ep_db_file_size_bytes` growing without compaction closing it.

**Replication**

- `kv_dcp_items_remaining` growing monotonically. Read the connection-type label to see which consumer is behind. Growth over time is the signal; the absolute value is workload-dependent.
- `xdcr_changes_left_total` growing monotonically. On a healthy pipeline this oscillates and returns toward zero; a trend line that only goes up is the alert, regardless of magnitude.

**Query Service**

- `n1ql_queued_requests` non-zero for a sustained period means every servicer is busy. Judgement call, not a documented default: a queue that never empties is worth a page even at low absolute depth, because it means the service has no headroom.
- `n1ql_errors` as a fraction of `n1ql_requests`, thresholded against baseline.
- The bucketed counters `n1ql_requests_1000ms` / `n1ql_requests_5000ms` map more directly onto an SLO than percentile series do.
- `n1ql_timeouts` — any rise is user-visible by definition.

**Index Service**

- `index_memory_used_total / index_memory_quota` approaching the quota; scans degrade as the index stops fitting in memory.
- `index_frag_percent` rising without falling back.

**Search Service**

- `fts_num_mutations_to_index` growing. A Search index that is behind returns stale results and throws no errors, so nothing else will tell you.
- `fts_tot_queryreject_on_memquota` — any non-zero value is user-visible rejection.

**Node health**

- Any node where `status` is not `healthy` or `clusterMembership` is not `active`, from `GET /pools/default`, excluding `warmup` during a planned restart. This is a state check, not a threshold.
- `sys_cpu_utilization_rate` per node, against baseline. In containers use the cgroup series instead.
- `kv_curr_connections` rising without a matching rise in `kv_ops` — connection leak or retry storm.

## Severity model

- **Warning** — trending badly, no user impact yet, actionable in business hours.
- **Page** — will become user-impacting within the remediation window if nobody acts.
- **Critical** — users are affected now.

Assigning a metric to a tier is a service-level decision, not a Couchbase one. It follows from your SLO and your on-call contract.

## Alert fatigue prevention

**Require duration before paging.** A single evaluation interval above a threshold is noise.

**Alert per node on resource pressure, aggregate for dashboards.** One node under memory pressure degrades the cluster; a cluster average hides it.

**Correlate before paging on memory.** Rising memory *plus* rising background fetches *plus* falling residency is a real working-set incident. Rising memory alone, stable and below the watermark, is a database using the RAM you bought it.

**Prune ruthlessly.** A rule that has never fired is untested, and a rule that fires constantly is already being ignored. Review both categories on a regular cadence.
