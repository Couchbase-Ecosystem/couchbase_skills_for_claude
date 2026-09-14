# Migration tooling

The tools for moving data into Couchbase, organized from simplest to most complex. Picking the right tool saves weeks of engineering — picking the wrong one means writing infrastructure that already exists.

> **Verify flags against the version you're running.** CLI tool options change between releases. The flags below are from the current Couchbase Server documentation; confirm against `--help` on the installed binary before scripting them.
>
> **Migration accelerator tooling is out of scope for this repository** by standing rule. Route those questions to Couchbase directly.

## Contents

- [cbmigrate](#cbmigrate--start-here-for-mongodb-and-dynamodb)
- [cbimport](#cbimport)
- [cbexport](#cbexport)
- [Deprecated tools](#deprecated-and-superseded-tools)
- [Backup tools](#cbbackupmgr)
- [Source-specific export](#source-specific-export-tools)
- [ETL frameworks](#etl-frameworks)
- [CDC tools](#cdc-tools)
- [Kafka and Spark connectors](#couchbase-connectors)
- [Picking the right tool](#picking-the-right-tool)

## `cbmigrate` — start here for MongoDB and DynamoDB

**This is the tool most migration conversations should start with, and it is the one most often missed.** `cbmigrate` is a purpose-built CLI for migrating into Couchbase from other platforms ([cbmigrate](https://docs.couchbase.com/server/current/cli/cbmigrate-tool.html)).

**Supported sources — three subcommands:**

| Subcommand | Source |
|---|---|
| `cbmigrate mongo` | MongoDB |
| `cbmigrate dynamodb` | DynamoDB |
| `cbmigrate hugging-face` | Hugging Face datasets |

**It is a separate download**, not part of the Couchbase Server install — get it from [couchbaselabs/cbmigrate](https://github.com/couchbaselabs/cbmigrate).

**Common flags across subcommands:**

| Flag | Purpose |
|---|---|
| `--cb-cluster` | Target Couchbase cluster connection string |
| `--cb-bucket` | Target bucket |
| `--cb-username` / `--cb-password` | Credentials |
| `--cb-batch-size` | Batch size for writes |
| `--cb-generate-key` | Document key generation template |

It also has options for SSL verification and for copying indexes from the source. Run `cbmigrate <subcommand> --help` for the full, version-accurate list — the source-specific flags (Mongo URI, DynamoDB region and table, and so on) differ per subcommand.

**Why it matters:** the alternative for MongoDB is `mongoexport` → transform script → `cbimport`, which is three moving parts and a transformation you maintain. `cbmigrate mongo` collapses that into one command with key generation built in. Reach for the hand-rolled pipeline only when you need a transformation `cbmigrate` can't express.

**What it doesn't do:** it is a bulk-migration tool, not a CDC pipeline. For ongoing sync during a zero-downtime migration, you still need dual-write or CDC — see `dual-write-and-cdc.md`. A common and effective pattern is `cbmigrate` for the initial load, then CDC for the delta.

## The Couchbase-native tools

These ship with Couchbase Server (self-managed) and are available for Capella targets too:

### `cbimport`

Bulk import from JSON or CSV files into Couchbase. The simplest possible loader.

**Format 1 — JSON lines (one document per line):**

```bash
cbimport json \
    --cluster couchbases://cb.example.com \
    --username Administrator \
    --password ... \
    --bucket app_data \
    --format lines \
    --dataset file:///path/to/users.jsonl \
    --generate-key "user::%id%"
```

The `--generate-key` template extracts a field from the document to form the key. `%id%` means use the document's `id` field; multiple field substitutions are supported.

**Format 2 — JSON array (one big array of documents):**

```bash
cbimport json --format list --dataset file:///path/to/users.json ...
```

Same idea but a single JSON array instead of newline-delimited.

**Format 3 — CSV:**

```bash
cbimport csv \
    --cluster ... \
    --bucket app_data \
    --dataset file:///path/to/users.csv \
    --generate-key "user::%id%"
```

CSV is row-oriented; each row becomes a document. Field names come from the header row.

**Documented options** ([cbimport json](https://docs.couchbase.com/server/current/tools/cbimport-json.html)):

| Flag | Notes |
|---|---|
| `--cluster` | Required — cluster node hostname |
| `--bucket` | Required |
| `--dataset` | Required — file path or URL |
| `--format` | `lines`, `list` or `sample` |
| `--username` / `--password` | Or certificate authentication |
| `--generate-key` | Key generation expression |
| `--threads` | **Documented default is 1** — raise it for faster loads |
| `--scope-collection-exp` | Scope/collection routing expression |
| `--errors-log` | Path for documents that failed to load |
| `--ignore-fields` | Comma-separated field names to exclude |
| `--limit-docs` | Stop after N documents |
| `--skip-docs` | Skip the first N documents |
| `--bucket-quota` | Memory quota, when using `--format sample` |

**`--threads` defaulting to 1 is the single most common cbimport performance mistake.** An import left at the default runs single-threaded no matter how large the cluster is.

`--limit-docs` and `--skip-docs` together are how you do a dry-run on a slice of a large file, or resume a partially-completed load.

**Performance:** `cbimport` is a single process. For very large loads, split the input file and run several imports in parallel against the same bucket, in addition to raising `--threads`.

**Limits:**
- File-based only — it does not stream from a source database. For MongoDB, DynamoDB or Hugging Face sources, use `cbmigrate` instead
- No transformation beyond key generation and field exclusion — documents load as-is
- One bucket per invocation

### `cbexport`

Mirror of `cbimport`. Exports a bucket / collection / scope to JSON or CSV.

```bash
cbexport json \
    --cluster ... \
    --bucket app_data \
    --format lines \
    --output /path/to/export.jsonl
```

Useful for:
- Initial export from one Couchbase cluster as input to another's import
- Backing up specific collections for migration validation
- Pulling data out for ETL pipelines that can't read Couchbase directly

### Deprecated and superseded tools

**`cbtransfer` is deprecated.** The current documentation carries an explicit deprecation notice directing users to **`cbdatarecovery`** instead, and separately recommends **XDCR** where the goal is moving data between two running clusters ([cbtransfer](https://docs.couchbase.com/server/current/cli/cbtools/cbtransfer.html)).

Do not recommend `cbtransfer` for new work. For Couchbase-to-Couchbase movement:

| Goal | Use |
|---|---|
| Move data between two running clusters | **XDCR** |
| Restore from a backup repository | **`cbbackupmgr restore`** |
| Recover data from an on-disk data directory | **`cbdatarecovery`** |

### `cbbackupmgr`

Couchbase's current backup and restore tool. Primarily for backup/restore, but usable for migration:

- Back up the source cluster
- Restore into the target (different cluster, version, or layout)

Useful for cluster version upgrades, hardware migrations, and cluster-to-cluster moves where the structure is preserved. Couchbase Server **8.0** adds configurable retention periods and automatic pruning of expired backups to the Backup Service, plus override protection for incremental backup deletion.

Verify edition availability and the exact subcommands against the docs for the version you're running.

## Source-specific export tools

The source database often has better export tooling than what you'd write yourself:

| Source | Recommended export tool |
|---|---|
| MongoDB | `mongoexport` (per-collection JSON), `mongodump` (BSON dumps) |
| PostgreSQL | `pg_dump` (full schema + data), `COPY ... TO ...` (CSV/text per-table) |
| MySQL | `mysqldump`, or `SELECT ... INTO OUTFILE` |
| Oracle | `expdp` (Data Pump), or `SQL*Plus` for CSV exports |
| SQL Server | `bcp` (bulk copy), or SSIS for complex exports |
| DynamoDB | AWS Data Pipeline, or DynamoDB Streams + custom Lambda |
| Cassandra | `cqlsh` `COPY TO`, or DSBulk |

Use these to export from source; transform with code or tooling; load with `cbimport`. This split (export-transform-import) is cleaner than trying to do all three in one pipeline.

## ETL frameworks

For migrations that need transformation (relational → document), an ETL framework saves time vs writing custom code.

### Open-source ETL tools

**Apache Nifi** — visual flow-based ETL. Has processors for many sources and a Couchbase sink. Good for one-shot or recurring migrations.

**Apache Airflow** — workflow orchestrator. Not strictly an ETL tool but commonly used to orchestrate migration tasks: export → transform → import → validate.

**Talend Open Studio** — visual ETL designer; commercial paid version available.

**Pentaho Data Integration (Kettle)** — similar visual ETL. Free community edition.

**Custom Python with pandas / polars** — for one-shot migrations where the transformation is well-defined, often the right answer. Read source, transform in DataFrame, write to Couchbase via SDK.

### Cloud ETL services

**AWS Glue** — managed ETL with Spark. Has a Couchbase connector (verify current support). Good if you're already AWS-native.

**Azure Data Factory** — managed ETL with Couchbase Connector (verify current support).

**Google Cloud Dataflow** — Apache Beam-based; build a custom pipeline.

These are good for ongoing pipelines but heavy for one-shot migrations.

## CDC tools

For ongoing source-to-target sync during dual-write migrations:

### Debezium

The most popular open-source CDC tool. Reads source DB transaction logs and emits changes to Kafka. A separate sink connector then writes from Kafka to Couchbase.

**Architecture:**

```
[Source DB] → [Debezium] → [Kafka] → [Couchbase Kafka Connector] → [Couchbase]
```

**Sources supported:**
- PostgreSQL
- MySQL
- MongoDB
- SQL Server
- Oracle (with extra setup)
- DB2

**Pros:**
- Battle-tested in production at scale
- Captures all changes (inserts, updates, deletes)
- Resumable — survives connector restarts
- Open-source

**Cons:**
- Real ops surface: Kafka cluster, Kafka Connect, Debezium connector, Couchbase connector — multiple things that can break
- Setup complexity is meaningful — plan a week minimum to get it stable
- Transformation between source and Couchbase format is via Single Message Transforms (SMTs) or Kafka stream processing — can get complex

### AWS DMS (Database Migration Service)

Managed CDC for AWS users, covering most RDBMS sources plus MongoDB.

**Check the supported-target list before planning around it.** Couchbase is not a first-party DMS target, and DMS's supported targets change. In practice DMS reaches Couchbase **indirectly** — for example by targeting Kafka (then the Couchbase Kafka sink connector) or S3 (then a `cbimport` load). Confirm the current target list in AWS's own documentation before committing to an architecture; do not assume a direct Couchbase target exists.

**Pros:**
- Managed — no Kafka cluster of your own to run
- Built-in monitoring

**Cons:**
- AWS-only
- Reaching Couchbase requires an intermediate hop, which reintroduces some of the complexity the managed service was meant to remove
- Transformation capabilities are limited compared to Debezium plus custom stream processing

### Custom CDC

For sources without good off-the-shelf CDC (or for simpler use cases), build your own:
- Poll the source's `updated_at` timestamps
- Subscribe to source's pub/sub (MongoDB changestreams, Postgres logical replication)
- Stream from a queue (Kafka, SQS, Pub/Sub)

Workable for small projects; doesn't scale to enterprise migration. Use Debezium for anything serious.

## Couchbase connectors

### Couchbase Kafka connector

If your migration involves Kafka anywhere (CDC, event streams), the **Couchbase Kafka connector** is the standard integration. It runs on Kafka Connect alongside Debezium or other source connectors, and ships both components ([Kafka connector](https://docs.couchbase.com/kafka-connector/current/index.html)):

- **Source connector** — streams documents out of Couchbase Server using the high-performance **Database Change Protocol (DCP)** and publishes the latest version of each document to a Kafka topic in near real time
- **Sink connector** — subscribes to Kafka topics and writes the messages into Couchbase Server

For migrations *into* Couchbase, the **sink** is what you want. The source connector matters when Couchbase is the origin — for instance, replicating out to a downstream system during a phased cutover.

Check the connector's compatibility page for supported Kafka and Couchbase Server versions before building on it.

### Couchbase Spark connector

For migrations involving Spark (Hadoop or data-lake migrations into Couchbase), the Couchbase Spark connector exposes Couchbase as a Spark DataFrame source and sink. Read a DataFrame from anywhere, write it to Couchbase through the connector. Useful when the transformation is genuinely large-scale — an in-memory join in a Python script does not survive contact with terabyte-scale source tables.

### Custom code via SDK

When the standard tools don't fit:

```python
# Python SDK 4.x. Verify symbols against your pinned SDK version;
# the *_multi operations are documented as a volatile API.
from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.options import ClusterOptions

cluster = Cluster.connect(
    CONN_STR,                                       # couchbases://... from env/secrets
    ClusterOptions(PasswordAuthenticator(USER, PASSWORD)),
)
collection = cluster.bucket("app").scope("_default").collection("users")

BATCH_SIZE = 1000          # tune against measured cluster load, not a fixed rule
batch = {}
for row in read_source():
    batch[f"user::{row['user_id']}"] = transform(row)
    if len(batch) >= BATCH_SIZE:
        collection.upsert_multi(batch)
        batch.clear()
if batch:
    collection.upsert_multi(batch)
```

In SDKs without `*_multi` helpers, express the same thing through the language's concurrency primitive — `Flux.fromIterable` in Java, `Promise.all` in Node, `Task.WhenAll` in .NET, a bounded goroutine pool in Go — and bound the concurrency either way.

This pattern works for:
- Custom source formats
- Complex transformations
- Migrations where standard tools choke (oddly-shaped data)

See `couchbase-app-integration` skill for the SDK details.

## Picking the right tool

Decision flow:

```
Source is MongoDB or DynamoDB?
├── One-shot → cbmigrate (mongo | dynamodb)          ← try this FIRST
└── Ongoing sync → cbmigrate for the bulk load,
                   then Debezium + Kafka + Couchbase Kafka sink for the delta

Source is a Hugging Face dataset?
└── cbmigrate hugging-face

Source is a JSON/CSV file?
├── No transformation needed → cbimport (raise --threads; default is 1)
└── Needs transformation → script: read file, transform, SDK multi-op

Source is relational?
├── One-shot → pg_dump/mysqldump + transform + cbimport
└── Ongoing  → Debezium + Kafka + Couchbase Kafka sink

Source is another Couchbase cluster?
├── Live clusters → XDCR
└── From a backup → cbbackupmgr restore
    (NOT cbtransfer — deprecated)

Source is something else (Cassandra, a warehouse, custom)?
└── Source's export tool + transform + cbimport, OR Spark connector at scale
```

## Estimating tool effort

Setup times below are **estimates** to calibrate expectations, not commitments.

| Tool | Setup time *(estimate)* | Maintenance burden |
|---|---|---|
| `cbmigrate` | Minutes to hours | None — one-shot |
| `cbimport` | Minutes | None — one-shot |
| Custom Python script | Hours-days | Low — runs once |
| ETL framework (Nifi, Airflow) | Days | Medium — operate the framework |
| Debezium + Kafka | 1-2 weeks | High — ongoing ops |
| AWS DMS (+ an intermediate hop to reach Couchbase) | Days | Low-medium — managed |
| Apache Spark migration | Days-weeks | High if Spark cluster isn't already running |

For one-shot migrations, prefer simpler tools. For ongoing sync (dual-write CDC), invest in real CDC tooling.

## Quick decision tree

- **Source is MongoDB, DynamoDB or Hugging Face?** → `cbmigrate` — check it before building anything else
- **One-shot, file-based source, no transformation?** → `cbimport` — and set `--threads`; the default is 1
- **One-shot, file source, needs transformation?** → Custom script + SDK
- **One-shot, complex source schemas?** → ETL framework (Nifi, Airflow, Spark)
- **Ongoing sync (dual-write or zero-downtime CDC)?** → Debezium + Kafka + Couchbase Kafka Connector
- **AWS-native, ongoing sync?** → AWS DMS
- **Couchbase to Couchbase, both live?** → XDCR. Not `cbtransfer` — it's deprecated in favour of `cbdatarecovery`, and XDCR is the documented recommendation for live clusters
- **Couchbase to Couchbase, from a backup?** → `cbbackupmgr restore`
- **Anything involving Kafka?** → Couchbase Kafka Connector as sink
