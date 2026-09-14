# Key metrics

Metric names below are the **Prometheus-exposition names** from the current Couchbase Server metrics reference. Couchbase's own UI labels differ from the metric names, and both differ from the legacy `/pools/default/buckets/<bucket>/stats` field names, so three different naming systems are in circulation. Always confirm a name against the metrics reference for the release you are monitoring before putting it in an alert rule.

## Contents

- [Naming changes you will trip over](#naming-changes-you-will-trip-over)
- [Memory](#memory)
- [Residency and disk fetches](#residency-and-disk-fetches)
- [Disk](#disk)
- [Operations](#operations)
- [Replication and DCP](#replication-and-dcp)
- [Query Service](#query-service)
- [Index Service (GSI)](#index-service-gsi)
- [Search Service](#search-service)
- [Node and system](#node-and-system)
- [Node health from the REST API](#node-health-from-the-rest-api)

## Naming changes you will trip over

**8.0 renamed the "Cache Miss Ratio" statistic to "Get Miss Ratio."** The rename is a correction, not a cosmetic change: since 7.6.2 the statistic has measured the proportion of `get` operations that fail because the key is **not present in the bucket at all** — a miss on the key, not a miss on the RAM cache. Any dashboard panel or runbook that reads "cache miss ratio means we are going to disk" has been wrong since 7.6.2 and is wrong under both names. Use background fetches (below) to measure going to disk.

**8.0 deprecated `kv_vb_ht_memory_bytes` in favour of `kv_vb_ht_memory_overhead`.** The old name measured per-hashtable overhead, not total hashtable memory, and the new name says so. Both metrics exist in 8.0; the old one will eventually be removed. Migrate now.

**8.0 fixed the scale of `kv_ep_mem_high_wat_percent_ratio` and `kv_ep_mem_low_wat_percent_ratio`,** which previously reported 0–0.01 where they should have reported 0–1. A threshold tuned against the old scale will not fire after upgrading. Re-check any rule using these two.

**8.0 deprecated the per-bucket stats endpoint.** `GET /pools/default/buckets/<bucket>/stats` is replaced by `GET /pools/default/stats/range/<metric_name>/<function-expression>`, with `POST /pools/default/stats/range` for multiple metrics; the XDCR equivalent `GET /pools/default/buckets/<source>/stats/<endpoint>` is replaced by `GET /pools/default/stats/range/<statistic>`. Anything scraping the old endpoints needs migrating.

**8.0 removed Memcached buckets** entirely (deprecated since 6.5.1). Dashboards with a bucket-type dimension should drop that series.

## Memory

| Metric | Meaning |
|---|---|
| `kv_mem_used_bytes` | Memory used by the bucket in the data service |
| `kv_ep_mem_high_wat` | High watermark, in bytes |
| `kv_ep_mem_low_wat` | Low watermark, in bytes |
| `kv_ep_mem_high_wat_percent_ratio` / `kv_ep_mem_low_wat_percent_ratio` | The watermarks as a fraction of quota (the legacy stat names are `ep_mem_high_wat_percent` / `ep_mem_low_wat_percent`) |
| `kv_ep_tmp_oom_errors` | Writes temporarily rejected — the client should back off and retry |
| `kv_ep_oom_errors` | Writes rejected outright |
| `kv_vb_ht_memory_overhead` | Hashtable memory overhead (8.0+; `kv_vb_ht_memory_bytes` on earlier releases) |

The mechanic to understand: when memory used crosses the **high watermark**, the data service begins **ejecting** documents from RAM to reclaim memory, and it keeps ejecting until usage falls below the **low watermark**. Ejection is normal and by design — Couchbase is not an in-memory-only store. What matters is whether the working set still fits, which you read from residency and background fetches, not from the watermark crossing itself.

`kv_ep_tmp_oom_errors` is the one to watch. Any sustained non-zero rate means clients are being told to back off, which shows up as application latency.

## Residency and disk fetches

| Metric | Meaning |
|---|---|
| `kv_ep_bg_fetched` | Background fetches — reads that had to go to disk because the document was not resident |
| `kv_ep_bg_meta_fetched` | Background metadata fetches |
| `kv_vb_perc_mem_resident_ratio` | Proportion of documents resident in RAM, by vBucket state |
| `kv_ep_num_non_resident` | Count of non-resident items |

**These, not "miss ratio," are how you tell whether the working set fits in RAM.** A rising background-fetch rate against a stable document count means the working set has outgrown available memory; the fix is more RAM or more nodes, not tuning.

Couchbase does not expose a ready-made cache-miss-ratio metric in the Prometheus exposition. If you want one, derive it — see the recording rule in `prometheus-grafana.md` — and name it something that says what it measures.

## Disk

| Metric | Meaning |
|---|---|
| `kv_ep_diskqueue_fill` | Rate at which mutations enter the disk write queue |
| `kv_ep_diskqueue_drain` | Rate at which they are written out |
| `kv_ep_diskqueue_items` | Items currently queued |
| `kv_ep_db_data_size_bytes` | Logical data size on disk |
| `kv_ep_db_file_size_bytes` | Actual file size on disk |
| `couch_docs_actual_disk_size` | Disk consumed by document data files |

If `fill` exceeds `drain` for any sustained period the queue grows, which turns into memory pressure and eventually into rejected writes. The gap between `kv_ep_db_data_size_bytes` and `kv_ep_db_file_size_bytes` is fragmentation waiting for compaction.

Node-level disk capacity is not a Couchbase metric — take it from the node exporter or the host agent you already run. Do not invent a Couchbase metric for it.

## Operations

| Metric | Meaning |
|---|---|
| `kv_ops` | Data service operations, labelled by operation |
| `kv_ops_failed` | Failed operations |
| `kv_cmd_lookup` / `kv_cmd_mutation` | Lookup and mutation command counts |
| `kv_collection_ops` | Operations broken down per collection |

`kv_collection_ops` is the one people forget. On a bucket holding several tenants' collections it is the only way to attribute load.

## Replication and DCP

| Metric | Meaning |
|---|---|
| `kv_dcp_items_remaining` | Items still to be sent on DCP streams, labelled by connection type |
| `kv_dcp_items_sent` | Items sent |
| `xdcr_changes_left_total` | XDCR backlog |

`kv_dcp_items_remaining` covers intra-cluster replication, views, indexing and XDCR producers alike — read the connection-type label before concluding which one is behind.

## Query Service

| Metric | Meaning |
|---|---|
| `n1ql_requests` | Request count |
| `n1ql_errors` / `n1ql_warnings` | Errors and warnings |
| `n1ql_active_requests` | Currently executing |
| `n1ql_queued_requests` | Waiting for a servicer |
| `n1ql_request_time` / `n1ql_service_time` | Cumulative request and service time |
| `n1ql_request_timer_p95`, `n1ql_request_timer_p99` | Latency percentiles |
| `n1ql_requests_250ms`, `_500ms`, `_1000ms`, `_5000ms` | Counts of requests exceeding each duration |
| `n1ql_timeouts` | Requests that timed out |

Note these are **not** suffixed `_total`, and the latency metric is **not** `n1ql_request_time_seconds` with a `quantile` label — the percentiles are separate named series. Rules written against Prometheus-idiomatic guesses will silently match nothing.

The bucketed counters (`n1ql_requests_250ms` and friends) are often more useful for SLO work than the percentile series, because they give you a straightforward "fraction of requests slower than X."

## Index Service (GSI)

| Metric | Meaning |
|---|---|
| `index_memory_used_total` | Memory used by the index service |
| `index_memory_quota` | Configured index memory quota |
| `index_resident_percent` / `index_avg_resident_percent` | Index residency |
| `index_frag_percent` | Index fragmentation |
| `index_disk_size` | Index size on disk |
| `index_num_rows_scanned` / `index_num_rows_returned` | Scan efficiency |
| `index_cache_misses` / `index_scan_cache_misses` | Index cache misses |

There is no `index_ram_percent` metric — compute utilisation as `index_memory_used_total / index_memory_quota`.

A large ratio of `index_num_rows_scanned` to `index_num_rows_returned` means the index is not selective for the queries hitting it. That is an index-design finding, which belongs in the query-optimisation workflow rather than an alert.

## Search Service

| Metric | Meaning |
|---|---|
| `fts_num_mutations_to_index` | Indexing backlog |
| `fts_num_bytes_used_ram` | RAM used by Search |
| `fts_num_bytes_ram_quota` | Search RAM quota |
| `fts_num_bytes_used_disk` | Disk used by Search |
| `fts_avg_queries_latency` | Average query latency |
| `fts_tot_queryreject_on_memquota` | Queries rejected for exceeding the memory quota |

A persistently growing `fts_num_mutations_to_index` means the Search Service cannot keep up with mutation volume — the index is serving stale results even though nothing is erroring.

## Node and system

| Metric | Meaning |
|---|---|
| `sys_cpu_utilization_rate` | CPU utilisation for the Couchbase processes |
| `sys_cpu_host_utilization_rate` | Host-wide CPU utilisation |
| `sys_cpu_cores_available` | Cores available to Couchbase |
| `sys_mem_actual_used` / `sys_mem_actual_free` | Host memory |
| `sys_mem_limit` | Memory limit |
| `sys_mem_cgroup_used` / `sys_mem_cgroup_limit` | cgroup memory, which is what matters in a container |
| `kv_curr_connections` | Open data-service connections |

In a container or Kubernetes pod, read the `sys_*_cgroup_*` series. The host-wide series describe the node, not your pod's budget, and will mislead you.

A jump in `kv_curr_connections` with no corresponding rise in `kv_ops` is the signature of a connection leak or a client retry storm.

## Node health from the REST API

Some state is not exposed as a metric and has to come from `GET /pools/default`, which returns per-node `status`, `clusterMembership`, `storageTotals` and `rebalanceStatus`, plus cluster `alerts`. That endpoint is current in 8.0 — it is the *bucket* stats endpoints that were deprecated, not this one.

Per node, the two fields to check:

- `clusterMembership` — `active` is normal; `inactiveFailed` means the node has been failed over; `inactiveAdded` means it is joining and not yet rebalanced in.
- `status` — `healthy` is normal; `warmup` means the node is loading data and not yet serving; `unhealthy` means the cluster cannot reach it.

Alert on any node that is not `active` and `healthy`, excluding `warmup` during a planned restart.
