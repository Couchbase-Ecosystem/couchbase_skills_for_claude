# XDCR configuration

## Contents

- [Setup sequence](#setup-sequence)
- [Remote cluster references](#remote-cluster-references)
- [Creating a replication](#creating-a-replication)
- [Filtering expressions](#filtering-expressions)
- [Deletion filters](#deletion-filters)
- [Changing a filter on a running replication](#changing-a-filter-on-a-running-replication)
- [Advanced settings and their real defaults](#advanced-settings-and-their-real-defaults)
- [Priority](#priority)
- [Monitoring a running replication](#monitoring-a-running-replication)

## Setup sequence

1. **Prepare both clusters** (network reachability, credentials, certificates).
2. **Create a remote cluster reference** — register the target cluster's address and credentials.
3. **Create a replication** — source bucket, target bucket, mappings, filter, settings.
4. **Monitor** until `changes_left` drains and stays near zero.

All three can be done from Couchbase Web Console, `couchbase-cli` (`xdcr-setup` for references, `xdcr-replicate` for replications), or the REST API. XDCR administration is not exposed by the official Couchbase MCP server.

## Remote cluster references

A reference records the target cluster's hostname (any node — XDCR discovers the rest), credentials, and the encryption level. Encryption levels:

- `none` — plaintext. Not appropriate for production.
- `half` — credentials encrypted, data in plaintext. Legacy; avoid.
- `full` — TLS for both authentication and data, with a certificate supplied. Required for replication that crosses an untrusted network.

## Creating a replication

The REST endpoint takes, among others:

| Parameter | Notes |
|---|---|
| `fromBucket`, `toBucket`, `toCluster` | The replication's endpoints |
| `filterExpression` | Matched against document ids, field names, values, and extended attributes on the source |
| `filterSkipRestream` | Whether changing `filterExpression` restarts the replication or lets it continue |
| `collectionsExplicitMapping` | Default `false`. `true` switches off implicit bucket-level mapping |
| `collectionsMigrationMode` | Default `false`. Routes documents out of the source default collection. Mutually exclusive with `collectionsExplicitMapping` |
| `colMappingRules` | JSON rules for either of the above |
| `conflictLogging` | 8.0+. JSON object; see `conflict-resolution.md` |
| `mobile` | `Off` (default) or `Active`. `Active` enables XDCR Active-Active with Sync Gateway 4.0+, and requires `enableCrossClusterVersioning` on all participating buckets. Available from 7.6.6 |
| `priority` | `Low`, `Medium`, or `High` |

The XDCR protocol must be Version 2 (`XMEM`, the Memcached binary protocol). There is no live alternative to choose.

Binary documents can be excluded from replication with the dedicated flag, independently of any `filterExpression`.

Source: [Creating XDCR Replications](https://docs.couchbase.com/server/current/rest-api/rest-xdcr-create-replication.html)

## Filtering expressions

XDCR Advanced Filtering expressions are a **subset of SQL++ expressions with some additions** — they are not SQL++, and several SQL++ constructs are unavailable. Matching is **case-sensitive**. A document is replicated only if the expression evaluates true for it.

What you can match on:

- `id` and `xattrs` in the document's metadata, via the reserved word `META`
- field names and values in the document body, nested to any depth

**Pattern matching** uses `REGEXP_CONTAINS`, not SQL `LIKE`:

```
REGEXP_CONTAINS(country, "France")
```

**Metadata access:**

```
REGEXP_CONTAINS(META().id, "airline_10")
REGEXP_CONTAINS(META().xattrs.color, "blue")
```

**Field existence** uses the single available collection operator:

```
EXISTS(country)
```

`EXISTS` is the *only* collection operator XDCR filtering provides — it tests whether a field is present in the document body. SQL++ offers many more; XDCR does not.

**Logical operators:** `AND`, `OR`, `NOT`. **Comparison operators:** a subset of SQL++'s. **Lookahead** is supported in patterns: positive with `char1(?=char2)`, negative with `char1(?!char2)`.

All of the operator keywords are reserved words; the filtering reference page carries the full reserved word list and a BNF grammar. Check it rather than assuming SQL++ syntax carries over.

Source: [XDCR Filtering Expressions](https://docs.couchbase.com/server/current/xdcr-reference/xdcr-filtering-expressions.html)

## Deletion filters

Separately from the filter expression, **deletion filters** control whether deleting a document on the source deletes its replica on the target. Each covers a specific deletion context. These interact with the filter expression, so read [Using Deletion Filters](https://docs.couchbase.com/server/current/xdcr-reference/xdcr-filtering-expressions.html) before assuming that a filtered replication propagates deletes the way you expect.

## Changing a filter on a running replication

The `filterSkipRestream` flag determines whether modifying `filterExpression` restarts the replication or lets it continue without restreaming. Either way, the change affects only mutations from that point forward:

- Documents already delivered to the target are **not** removed when a filter is narrowed. They persist on the target until you delete them.
- Widening a filter does not retroactively replicate documents whose mutations have already passed the filter; only future mutations of those documents will cross.

## Advanced settings and their real defaults

From [XDCR Advanced Settings](https://docs.couchbase.com/server/current/xdcr-reference/xdcr-advanced-settings.html):

| Setting (UI name) | Default | Range | Notes |
|---|---|---|---|
| XDCR Protocol | Version 2 (`XMEM`) | fixed | Memcached binary protocol |
| Compression Type | `Auto` or `None` | — | `Auto` attempts compression when the target runs Couchbase Server 5.5 or later; snappy is used only when the encoded size is smaller than the raw size |
| Source Nozzles per Node | 2 | 1–100 | Must be **less than or equal to** Target Nozzles per Node |
| Target Nozzles per Node | 2 | 1–100 | Must be **greater than or equal to** Source Nozzles per Node |
| Checkpoint Interval | 600 s | 60–14400 | Shorter means less rework on restart but more resource use |
| Batch Count | 500 | 500–10000 | A batch completes when count *or* size is reached first |
| Batch Size | 2048 KB | 10–10000 KB | |
| Failure Retry Interval | 10 s | 1–300 | |
| Optimistic Replication Threshold | 256 bytes | 0–20 MB | Documents **larger** than this have target metadata fetched so conflict resolution runs on the source; smaller ones are sent without it and are resolved only on the target. **Applies only when `enableCrossClusterVersioning` is disabled** |
| Statistics Collection Interval | — | — | How often XDCR statistics update |
| Network Usage Limit | 0 (no limit) | — | MB/s for the **entire cluster**; the per-node limit is that divided by node count. Applies to mutations only, not topology or statistics traffic |
| Logging Level | — | Error, Info, Debug, Trace | 8.0 also adds `genericServicesLogLevel` for per-service levels |

A combination of source and target nozzle counts that is too high for the configured XDCR Maximum Processes produces a warning in the Web Console. Raise nozzle counts in small steps and watch source CPU.

Note that a low optimistic replication threshold increases metadata fetch latency but may reduce the number of actual replications; a high one lowers per-document latency but can overwhelm the network or the target.

## Priority

`priority` is `Low`, `Medium`, or `High`, and controls resource allocation to the replication relative to other work. Lower it during a foreground traffic spike to protect the serving workload, then raise it again once the source catches up. This manages contention; it does not increase total throughput.

## Monitoring a running replication

The statistics that matter:

- **`changes_left`** — mutations not yet replicated. Near zero in steady state. Consistently non-zero and growing means the replication cannot keep up.
- **`docs_written`** — cumulative mutations replicated successfully.
- **`docs_failed_cr_source`** — mutations where the source lost conflict resolution because the target's version won. Normal in active-active; unexpected in active-passive.
- **`data_replicated`**, **`bandwidth_usage`**, **`rate_replication`** — volume and rate.
- **`subdoc_cmd_docs_skipped`** — a Prometheus stat. In an active-active-with-Sync-Gateway deployment, this is the **only** signal that a document was silently skipped for having more than 10 user xattrs. See `topology.md`.

On **8.0+**, a cluster can also list **incoming replications** — the streams originating on remote clusters and targeting the local cluster, with their configuration and status, from the UI or REST API. Use it to verify that a topology is wired the way you think it is, from both ends.

**xdcrDiffer** (8.0+, shipped in the Server installation package; previously built from the GitHub source) compares document data between source and target clusters and reports differences in content, metadata, or presence. It is the right tool for proving replication fidelity, rather than eyeballing document counts.
