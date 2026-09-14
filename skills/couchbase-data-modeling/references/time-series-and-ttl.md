# Time-series and TTL

Workloads dominated by time-stamped writes — metrics, events, logs, sessions, IoT data, audit trails — have their own modeling patterns. Couchbase is not a dedicated time-series database, but with the right model it handles time-series workloads well. How far it scales is a sizing question, not a modeling one — use the `couchbase-sizing` skill rather than assuming a throughput ceiling.

## Contents

- [What makes time-series workloads different](#what-makes-time-series-workloads-different)
- [Key design for time-series](#key-design-for-time-series)
- [Document granularity: per-point vs bucketed](#document-granularity-per-point-vs-bucketed)
- [How TTL actually works](#how-ttl-actually-works)
- [TTL strategies](#ttl-strategies)
- [Aggregation strategies](#aggregation-strategies)
- [Events / audit logs](#events--audit-logs)
- [IoT-specific patterns](#iot-specific-patterns)
- [Anti-patterns](#anti-patterns)
- [Quick decision tree](#quick-decision-tree)

## What makes time-series workloads different

- **Write-heavy:** typically 95%+ writes
- **Append-only or near-append-only:** existing data rarely changes
- **Time-windowed queries:** "last 24 hours of metrics for node X"
- **Retention-bounded:** old data has declining value; eventually it's deleted
- **Aggregate-friendly:** the user typically wants downsampled views, not raw points

Modeling for these workloads requires thinking about: key design (to avoid hot shards), document granularity (one-point-per-doc vs bucketed), TTL strategy (per-doc vs collection-rotation), and aggregation strategy (read-time vs precomputed).

## Key design for time-series

The naive key — `metric::cpu::2026-05-21T14:32:18.473Z` — works at low write rates but fails at scale: all writes within the same millisecond hash near the same vBucket → hot shard.

**Pattern: high-entropy prefix**

```
metric::<hash-of-source>::cpu::<timestamp>
```

The source (node, host, sensor ID) provides natural entropy. As long as you have many concurrent sources, the hash distributes evenly.

**Pattern: ULID-based keys**

```
metric::cpu::01HXKZ7M8YQNT9N5J2VCABCDEF
```

ULIDs are time-sortable AND have built-in randomness. The first chunk is the timestamp; the rest is entropy. Best of both worlds.

**Pattern: bucket-stable keys for downsampled summaries**

```
metric_minute::cpu::node-7::2026-05-21T14:32  (one doc per minute per source)
metric_hour::cpu::node-7::2026-05-21T14      (one doc per hour per source)
```

These are bigger windows, so the write rate per key is naturally lower and hot-sharding is less of a concern.

## Document granularity: per-point vs bucketed

The single biggest sizing decision in time-series modeling.

### Pattern A — One document per data point

```json
// metric::cpu::node-7::2026-05-21T14:32:18.473Z
{ "metric": "cpu", "node": "node-7", "ts": "2026-05-21T14:32:18.473Z", "value": 0.73 }
```

**Pros:**
- Simple model, easy to reason about
- Per-point access via direct KV
- Per-point TTL is straightforward

**Cons:**
- Massive document count (1 metric × 10 nodes × 1 point/sec = 864K docs/day per metric)
- High per-document overhead (metadata, key storage)
- Storage cost dominated by overhead, not data

Use Pattern A when: write rates are modest (< 1K/sec total) and per-point access is needed.

### Pattern B — Time-bucketed documents

```json
// metric::cpu::node-7::2026-05-21T14:32
{
  "metric": "cpu",
  "node": "node-7",
  "bucket_start": "2026-05-21T14:32:00Z",
  "bucket_end": "2026-05-21T14:32:59Z",
  "points": [
    { "ts": "...:00.123Z", "value": 0.71 },
    { "ts": "...:01.045Z", "value": 0.73 },
    ...
  ],
  "count": 60,
  "min": 0.69, "max": 0.81, "avg": 0.74   // optional pre-aggregates
}
```

One document per minute per metric per node. 60 points become one doc.

**Pros:**
- 60× fewer documents (or whatever your bucket size is)
- Pre-aggregates available without scanning
- Better RAM utilization (fewer keys in memory)

**Cons:**
- Appending a point to the bucket document is a read-modify-write. The Sub-Document API's array-append avoids shipping the whole document over the network, but the server still rewrites and re-replicates the full document
- Bucket boundaries are arbitrary — queries spanning a boundary need to read 2 docs
- More complex code

Use Pattern B when: write rate is high (> 1K/sec) and per-point access isn't needed.

### The bucket size question

Pick the smallest bucket that satisfies your reads without exceeding ~1 MB per document:

- 1-minute buckets for second-resolution metrics with retention < 7 days
- 1-hour buckets for second-resolution metrics with retention 1-30 days
- 1-day buckets for minute-resolution metrics with retention up to a year

Math: at 1 point per second with ~100 bytes per point, a 1-hour bucket is roughly 360 KB — fine. A 1-day bucket would be roughly 8.6 MB: still under the 20 MB hard limit, but far past the practical target and painful to rewrite on every append.

## How TTL actually works

Before picking a strategy, know the mechanics — several common bugs come from not knowing them.

**Where expiry can be set.** A document carries its own expiration in its metadata. A collection and a bucket each have a `maxTTL` setting, which is `0` (no automatic expiration) by default.

**Precedence.** A non-zero expiration set at a *lower* level takes precedence over a higher level: document beats collection, collection beats bucket. Two important exceptions:

- A document's expiration **cannot exceed** the collection's or bucket's `maxTTL`. Setting a 30-day expiry in a collection with a 1-day `maxTTL` does not get you 30 days.
- Setting a document's expiration to `0` does **not** make it permanent if the collection or bucket has a non-zero `maxTTL`. "No expiry" at the document level means "inherit", not "never".
- A collection `maxTTL` of `0` inherits the bucket's setting. A collection `maxTTL` of `-1` explicitly opts out of bucket inheritance, so documents in that collection don't expire even when the bucket has a `maxTTL`.

**When documents actually disappear.** An expired document is removed when a query or read touches it, when the expiry pager runs, or during auto-compaction. So "expired" and "deleted" are not the same instant — expired documents can still occupy disk between those events, and a naive `SELECT COUNT(*)` will not see them but a disk-usage graph still will.

**Tombstones.** After deletion Couchbase keeps a tombstone, which is itself removed on the metadata purge interval. Plan disk headroom for tombstones on high-churn collections.

**The classic bug:** the update that silently resets expiry. A full-document replace or upsert writes new metadata, and unless the write preserves the expiration the document's TTL is reset or cleared. If you touch documents that are supposed to expire, make sure the write path preserves expiry.

## TTL strategies

Three approaches, in increasing order of operational sophistication.

### Strategy 1 — Per-document TTL

Set expiry at write time through the SDK's upsert/insert options (every SDK exposes an `expiry` option, taking either a duration or an absolute instant):

```
upsert("session::42::abc123", value, expiry = 3600 seconds)
```

**Use for:** sessions, short-lived caches, rate-limit counters — anything with a known short lifespan decided at write time.

**Limit:** the expiry pager has to do real work per document. At very high write rates with very short TTLs, expiry cleanup and the resulting tombstone churn become their own load.

### Strategy 2 — Per-collection TTL

Give the collection a `maxTTL`, set when you create the collection or updated afterwards through the UI, REST API, or CLI. Every write to that collection then gets that expiry unless the document sets a shorter one.

**Use for:** ephemeral collections like `sessions` or `temp_data`, where everything in the collection shares a lifecycle. This is more robust than per-document TTL because it can't be forgotten by one code path.

### Strategy 3 — Collection rotation

For long-running time-series with month-scale retention, neither per-doc nor per-collection TTL is efficient — the cluster spends real CPU expiring billions of docs.

Better: rotate collections by time window. Remember the cluster ceiling of 1000 collections — a monthly rotation is fine for decades, a daily rotation is not.

```
metrics_2026_05    (current month — writes go here)
metrics_2026_04    (previous month — reads only)
metrics_2026_03    (2 months ago — reads only)
metrics_2026_02    (3 months ago — about to drop)
```

On the first of each month: create the new collection, point writes at it, drop the oldest. Collection-level drop is essentially instant compared to per-doc deletion of millions of items.

Application code needs to know which collection(s) to query for a given time range. Typical: maintain a small config doc mapping time ranges to collections.

**Use for:** anything with retention > 30 days and steady write rate.

## Aggregation strategies

### Pattern: query-time aggregation

```sql
SELECT SUBSTR(ts, 0, 13) AS hour, AVG(value) AS avg_value
FROM metrics
WHERE metric = 'cpu' AND node = 'node-7'
  AND ts >= '2026-05-21T00:00:00Z' AND ts < '2026-05-22T00:00:00Z'
GROUP BY SUBSTR(ts, 0, 13);
```

Note the function used. Couchbase SQL++ has **no `date_trunc`** — that's Postgres. It has `DATE_TRUNC_STR(date, part)` for date strings and `DATE_TRUNC_MILLIS(millis, part)` for epoch timestamps, but their `part` argument only goes down to `week` / `iso_week` (the full set is millennium, century, decade, year, quarter, month, week, iso_week). For hour- or minute-level bucketing of ISO-8601 strings, prefix truncation with `SUBSTR` is the straightforward approach — and it's index-friendly if you store the truncated value as its own field.

Simple and flexible, but slow over millions of points. Fine for ad-hoc analysis; bad for a dashboard refreshing every 10 seconds.

### Pattern: pre-aggregated bucket documents

Store hour-level and day-level summary docs alongside the raw points:

```
metric_minute::cpu::node-7::2026-05-21T14:32     { raw points + min/max/avg/count }
metric_hour::cpu::node-7::2026-05-21T14          { aggregated from minutes }
metric_day::cpu::node-7::2026-05-21              { aggregated from hours }
```

Maintained via Eventing function triggered on minute-doc writes, or via a periodic batch job.

Query at the right granularity: dashboards over the last hour use minute docs; reports over the last week use hour docs; quarterly trends use day docs.

### Pattern: downsample-then-discard

After computing hour and day aggregates, optionally delete the raw minute docs to save storage. Keep aggregates indefinitely (cheap, small).

## Events / audit logs

Audit logs are time-series with different requirements:

- Per-event-doc model (Pattern A) because per-event access matters (for an investigation)
- Long retention (months to years for compliance)
- Indexable by event type, user, target resource

Model:

```json
// event::login::user_42::01HXKZ7M8YQNT9N5J2VCABCDEF
{
  "type": "login",
  "user_id": 42,
  "ts": "2026-05-21T14:32:18.473Z",
  "ip": "10.0.0.42",
  "user_agent": "...",
  "success": true
}
```

Indexes:
- `CREATE INDEX ix_event_user ON events(user_id, ts)` — "all events for user X in time range"
- `CREATE INDEX ix_event_type ON events(type, ts)` — "all login events in time range"

Use Strategy 3 (collection rotation) for the actual retention, because you'll be retaining millions of these.

## IoT-specific patterns

If devices report telemetry at high rate, every device should produce its own key prefix to avoid hot-sharding:

```
telemetry::<device_id>::<bucket_start_ts>
```

If you have 10K devices each reporting once per second, that's 10K writes/sec spread across 10K distinct keys → naturally balanced.

For per-device queries, the key prefix makes the query trivially efficient via `LIKE 'telemetry::device_42::%'` patterns.

For cross-device queries (e.g., "what was the average temperature across all devices in the last hour?"), maintain a pre-aggregated summary collection updated by Eventing or batch.

## Anti-patterns

- **One document per metric type that grows forever** (`metric::cpu` with all CPU points ever appended to it) — write hot spot, exceeds size limit quickly
- **Sequential timestamps as full key** — guaranteed hot-sharding
- **Per-doc TTL on millions of high-rate docs** — expiry pager work and tombstone churn become the bottleneck; use collection rotation
- **Assuming expiry 0 means permanent** — it means "inherit from the collection/bucket `maxTTL`". Use `-1` on the collection to genuinely opt out
- **A write path that drops expiry** — a full replace resets the document's TTL unless it preserves expiration
- **No retention strategy** — disk fills, ops gets paged
- **Indexing every field of every event doc** — index bloat. Index only the fields you query

## Quick decision tree

- **Low write rate, per-point access needed?** → Pattern A (per-point docs), per-doc TTL
- **High write rate, no per-point access?** → Pattern B (bucketed docs), collection-level TTL or rotation
- **Retention > 30 days at steady write rate?** → Collection rotation strategy
- **Need dashboards over recent data?** → Pre-aggregated minute / hour / day summary docs
- **Need ad-hoc analytical queries?** → the Analytics service (EE), or Capella Analytics / Couchbase Enterprise Analytics, all of which isolate analytical work from the operational workload
- **IoT with many sources?** → Per-device key prefix for natural sharding
- **Audit / compliance logs?** → Per-event docs, secondary indexes by user/type/resource, collection rotation
