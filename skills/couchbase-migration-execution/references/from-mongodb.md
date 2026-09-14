# Migrating from MongoDB

MongoDB-to-Couchbase is the most common document-database migration to Couchbase. Both are JSON document stores, so the shape translates relatively directly — but there are real differences in modeling, query language, indexing, and operational primitives that need handling.

> **Start with `cbmigrate mongo`.** Couchbase ships a purpose-built MongoDB migration CLI; the `mongoexport` + transform + `cbimport` pipeline below is the fallback for cases it can't express, not the default. See the tooling section.
>
> **Verify SDK and CLI symbols against your pinned versions** before using any code here.

## Contents

- [Concept mapping](#concept-mapping)
- [Schema differences worth flagging](#schema-differences-worth-flagging)
- [Tooling for MongoDB → Couchbase](#tooling-for-mongodb--couchbase)
- [Modeling considerations](#modeling-considerations)
- [Query translation](#query-translation)
- [Transactions](#transactions)
- [Operational differences](#operational-differences)
- [Common MongoDB-to-Couchbase migration pitfalls](#common-mongodb-to-couchbase-migration-pitfalls)
- [A typical MongoDB migration timeline](#a-typical-mongodb-migration-timeline)
- [Quick decision tree](#quick-decision-tree)

## Concept mapping

| MongoDB | Couchbase | Notes |
|---|---|---|
| Cluster | Cluster | Roughly equivalent |
| Database | Bucket | MongoDB databases are namespaces; buckets are heavier (own memory budget) |
| Collection | Collection (within a scope) | Scopes and collections require Couchbase Server **7.0+**; on 6.x there is only the bucket |
| Document | Document | JSON in both |
| `_id` field | Document key | MongoDB auto-generates ObjectId; Couchbase uses any string |
| Index | GSI index | Different syntax (SQL++ `CREATE INDEX` vs MongoDB `createIndex`) |
| Replica Set | Cluster with replicas | Couchbase replicates via vBuckets, not replica sets per se |
| Sharding | Built-in (vBuckets) | No manual shard key needed; vBuckets auto-distribute |
| Change Streams | Eventing functions | Server-side reactions to mutations |
| `find()` | KV `get` or SQL++ `SELECT` | Pick KV when filtering by the key; SQL++ otherwise |
| Aggregation pipeline | SQL++ with subqueries, or the Analytics Service | SQL++ covers most aggregation needs |
| `$lookup` (joins) | SQL++ `JOIN`, or denormalization | SQL++ joins are real but cost more than a denormalized read |
| GridFS (binary blobs) | Not a direct equivalent | Documents are capped at **20 MB**; put binaries in object storage and reference them |
| Transactions | Couchbase distributed ACID transactions, via the SDK | Documented for the C++, .NET, Go, Java, Kotlin, Node.js, PHP, Python and Scala SDKs. Documents in a transaction must be under 10 MB, and NTP is required |

## Schema differences worth flagging

**MongoDB's `_id` is an `ObjectId` by default.** Couchbase document keys are strings. The mapping options:

1. **Use `_id.toString()` as the Couchbase key** — straightforward, opaque
2. **Use a more meaningful key derived from the document** — e.g., `user::<email>` instead of `user::507f1f77bcf86cd799439011`. Better for debugging

For migrations preserving identity (existing references in other systems), use option 1. For new applications building on top of the migration, option 2 is more operable.

**MongoDB's flexible-schema reality:** the same collection can have wildly varying document shapes if discipline wasn't enforced. Before migrating, run a schema audit:

```javascript
// In MongoDB
db.users.aggregate([{ $sample: { size: 1000 } }, { $project: { keys: { $objectToArray: "$$ROOT" }}}, {$unwind: "$keys"}, {$group: { _id: "$keys.k", count: { $sum: 1 }}}])
```

The output is "for a 1000-doc sample, here's how often each field appears." Fields with low occurrence are usually accidental — decide whether to keep or drop.

On the Couchbase side, the SQL++ `INFER` statement samples a collection and reports the shapes it finds — run it post-migration to verify the actual schema matches expectations. Couchbase Server **8.0** extends `INFER` with `array_sample_size`, `max_nesting_depth` and `flags` options, and it now returns `meta().id()` automatically.

## Tooling for MongoDB → Couchbase

### Preferred: `cbmigrate mongo`

Couchbase ships a dedicated MongoDB migration command ([cbmigrate](https://docs.couchbase.com/server/current/cli/cbmigrate-tool.html)). It reads from MongoDB and writes to Couchbase in one step, with key generation and index copying built in — no intermediate file, no transform script to maintain, no ObjectId-in-the-key problem to solve by hand.

```bash
cbmigrate mongo \
    --cb-cluster couchbases://cb.example.com \
    --cb-username Administrator \
    --cb-password "..." \
    --cb-bucket app_data \
    --cb-generate-key "user::%_id%" \
    --cb-batch-size 1000
```

Run `cbmigrate mongo --help` for the version-accurate flag list — the MongoDB connection and collection-selection flags in particular are specific to this subcommand and change between releases. `cbmigrate` is a **separate download** from [couchbaselabs/cbmigrate](https://github.com/couchbaselabs/cbmigrate), not part of the server install.

Use `cbmigrate` unless you need a transformation it can't express. Then, and only then, fall back to the pipeline below.

### Fallback: `mongoexport` + cbimport

```bash
# Step 1: Export from MongoDB
mongoexport \
    --uri="mongodb://source-host:27017/mydb" \
    --collection=users \
    --out=users.jsonl

# Step 2: (Optional) transform — adjust field names, key format, etc.
# E.g., a quick Python script that reads users.jsonl and writes transformed.jsonl

# Step 3: Import to Couchbase
cbimport json \
    --cluster couchbases://cb.example.com \
    --username Administrator \
    --password "..." \
    --bucket app_data \
    --scope-collection-exp _default.users \
    --format lines \
    --dataset file://transformed.jsonl \
    --generate-key "user::%_id%" \
    --threads 8
```

mongoexport writes JSON lines (one doc per line); cbimport reads them directly with `--format lines`. **Set `--threads` explicitly — cbimport's documented default is 1**, which will leave a large cluster idle. `--limit-docs` and `--skip-docs` are useful for dry runs on a slice of the file.

**Key generation:** `%_id%` substitutes the document's `_id` field into the Couchbase key. If the document has `_id: ObjectId("...")`, the resulting key is `user::ObjectId("...")` — usually you want to convert this to a string first in the transform step.

### Ongoing sync: Debezium MongoDB connector

For zero-downtime migrations, Debezium's MongoDB source connector reads from the MongoDB oplog (or change streams) and emits to Kafka. A Couchbase sink consumes Kafka and writes to the target.

**Setup outline:**

```
[MongoDB] --[oplog]--> [Debezium MongoDB connector] --> [Kafka topic]
                                                            |
                                                            v
                                            [Couchbase Kafka Connector]
                                                            |
                                                            v
                                                       [Couchbase]
```

Connector configs are JSON; the Debezium docs at https://debezium.io/documentation/ have current schema. Plan a week minimum to get this stable.

### Commercial sync tools

Some commercial integration products offer direct MongoDB-to-Couchbase sync without a Kafka intermediate — less operational surface, at the price of a commercial dependency. Verify current Couchbase support directly with the vendor rather than assuming it; connector coverage changes.

## Modeling considerations

The temptation: "MongoDB documents are JSON, Couchbase documents are JSON, just dump them across." This works as a starting point but often misses Couchbase-specific optimization opportunities.

**Things to consider during migration (cross-reference `couchbase-data-modeling` skill):**

1. **Embedded vs referenced** — MongoDB conventions may have over-embedded (huge user docs with all their activity) or over-referenced (small docs requiring many JOINs). The migration is a chance to fix this
2. **Key design** — MongoDB ObjectIds are opaque. Better keys (`user::<email>` or ULIDs with type prefixes) help operability
3. **Scopes & collections** — if MongoDB's "database" was being used as a tenant boundary, consider mapping to Couchbase scopes
4. **TTL on ephemeral docs** — Couchbase supports per-document and per-collection TTL; MongoDB has TTL indexes. The concepts map, but confirm the exact expiry semantics for your server version
5. **Indexes** — not every MongoDB index needs a Couchbase counterpart. Run the Index Advisor (`ADVISE` in SQL++, or the UI's Index Advisor) against your representative query set and build what it identifies
6. **Document size** — Couchbase's documented maximum document size is **20 MB** (MongoDB's BSON limit is smaller, so this is rarely binding, but GridFS-style splitting doesn't carry over)

## Query translation

MongoDB queries don't translate 1:1 to SQL++. Common patterns — note that every example below should use **bound parameters** in application code, never string interpolation:

### Find by ID

```
// MongoDB
db.users.findOne({_id: ObjectId("...")})
```

```sql
-- Couchbase via KV (preferred — a direct hash lookup, no index, no query engine)
-- collection.get("user::<id>") in the SDK

-- Couchbase via SQL++ (works, but strictly more work than the KV get)
SELECT u.* FROM `app`.`_default`.`users` u WHERE META(u).id = $key
```

### Filter by field

```
// MongoDB
db.users.find({tier: "gold"})
```

```sql
-- Couchbase
SELECT u.* FROM `app`.`_default`.`users` u WHERE u.tier = $tier
```

Requires a GSI index on `tier`:

```sql
CREATE INDEX ix_users_tier ON `app`.`_default`.`users`(tier);
```

### Aggregation

```
// MongoDB
db.orders.aggregate([
  { $match: { status: "complete" }},
  { $group: { _id: "$customer_id", total: { $sum: "$amount" }}},
  { $sort: { total: -1 }},
  { $limit: 10 }
])
```

```sql
-- Couchbase SQL++
SELECT o.customer_id, SUM(o.amount) AS total
FROM `app`.`sales`.`orders` o
WHERE o.status = $status
GROUP BY o.customer_id
ORDER BY total DESC
LIMIT 10
```

Considerably cleaner in SQL++, since it's SQL-shaped rather than a pipeline.

### Joins (MongoDB `$lookup`)

```
// MongoDB
db.orders.aggregate([
  { $lookup: {
      from: "users",
      localField: "user_id",
      foreignField: "_id",
      as: "user"
  }}
])
```

```sql
-- Couchbase SQL++
SELECT o.*, u.name AS user_name
FROM `app`.`sales`.`orders` o
JOIN `app`.`_default`.`users` u ON META(u).id = "user::" || o.user_id
```

Joins work in Couchbase, but consider denormalization if this is a hot path — see the `couchbase-data-modeling` skill.

### Text search

```
// MongoDB (with text index)
db.products.find({$text: {$search: "wireless mouse"}})
```

```
// Couchbase: create a Search Service index over the field,
// then query it through the SDK's search API or the Search REST endpoint.
```

The Search Service is more flexible than MongoDB text search: fuzzy matching, per-language analyzers, custom analyzers, and — in Couchbase Server **8.0** — synonym collections, custom document filters, partition selection, **BM25** scoring alongside tf-idf, and Search vector indexes for hybrid vector/text search.

### Change Streams

```
// MongoDB
const changeStream = db.users.watch();
changeStream.on('change', (change) => { ... });
```

```
// Couchbase
// Use Eventing functions (server-side JS) instead — see couchbase-mcp skill
// Functions react to mutations and can write to other collections, call HTTP endpoints, etc.
```

Couchbase Eventing is more capable than change streams (it can transform, filter and fan out) but runs server-side. If your application needs to react to changes in application code, the route is the **Database Change Protocol (DCP)** — most practically consumed through the **Couchbase Kafka connector's source mode**, which streams document changes to a Kafka topic. Couchbase Server 8.0 adds an **OnDeploy** handler that runs once at function deployment before mutation processing begins.

## Transactions

MongoDB has multi-document transactions in replica sets and sharded clusters.
Couchbase has distributed ACID transactions built into the SDK, documented for the **C++, .NET, Go, Java, Kotlin, Node.js, PHP, Python and Scala** SDKs ([Transactions](https://docs.couchbase.com/server/current/learn/data/transactions.html)).

Both work similarly: begin → operations → commit/abort, with the SDK managing retries. Code patterns translate; the specific API differs by SDK. Two Couchbase constraints to carry into the design: documents in a transaction must be **under 10 MB**, and the cluster requires **NTP-synchronized clocks**. See the `couchbase-app-integration` skill's `transactions-app-side.md` for the patterns.

## Operational differences

| Concern | MongoDB | Couchbase |
|---|---|---|
| Connection from app | mongoose / native driver | Couchbase SDK (see `couchbase-app-integration`) |
| User management | `createUser` / `grantRolesToUser` | Couchbase RBAC users and roles. 8.0 adds SQL++ `CREATE`/`ALTER`/`DROP` statements for users and groups |
| Backup | `mongodump` / Atlas backups | The Backup Service and `cbbackupmgr` |
| Monitoring | Atlas / Cloud Manager | Cluster statistics and Prometheus-compatible metrics (see `couchbase-mcp`) |
| Sharding | Manual shard key | Automatic via vBuckets — no shard key to choose |
| Replication | Replica sets | Replicas per bucket (0-3). Replicas do **not** serve ordinary reads |

## Common MongoDB-to-Couchbase migration pitfalls

- **Treating ObjectId as a magic key:** Couchbase keys are just strings. Define a key naming convention; don't carry ObjectId opacity forward unless you have to
- **Keeping MongoDB's `_id` field in the document body:** redundant. Couchbase key IS the access path. You can store it in the body for queries via `META().id`, but don't keep the MongoDB-style `_id` field by reflex
- **Translating every MongoDB index to a Couchbase index:** MongoDB collections often have many indexes that aren't used. Profile queries on the new system; build only what's needed
- **Using SQL++ for everything:** if the access pattern is "get by key," a KV `get` is a direct hash lookup with no index and no query engine. Use SQL++ when filtering or aggregating
- **Ignoring scopes and collections:** Couchbase Server **7.0+** has scopes and collections for organizing data within a bucket. MongoDB has no scope equivalent, so this is a structural decision the migration forces you to make — and with a documented **maximum of 30 buckets per cluster**, mapping each MongoDB database to its own bucket does not scale. Map databases to scopes and collections to collections
- **Building the hand-rolled pipeline before checking `cbmigrate`:** the most common wasted week in a MongoDB migration

## A typical MongoDB migration timeline

For a moderate MongoDB-to-Couchbase migration (10-100 GB):

| Phase | Duration | Activities |
|---|---|---|
| Planning | 1-2 weeks | Schema audit, modeling decisions, sizing, approach |
| Tooling setup | 3-5 days | Test `cbmigrate mongo` on sample data (or the fallback pipeline if needed) |
| Dry run | 1 week | Migrate 10% sample to staging; validate; iterate |
| Schema iteration | 1-2 weeks | Adjust target model based on findings |
| Staging migration | 1 week | Full migration to staging; full validation |
| Dual-write or CDC setup | 1-2 weeks | If zero-downtime; Debezium + Kafka path |
| Soak period | 2-4 weeks | Both DBs in sync; validate continuously |
| Cutover | 1 day | Switch app traffic |
| Soak post-cutover | 2-4 weeks | MongoDB still running, read-only |
| Decommission | 1 day | Retire MongoDB |

Total: 8-16 weeks for production-grade migrations *(estimate — calibrate against the customer's actual data volume, transformation complexity and change-control process)*.

## Quick decision tree

- **One-shot migration with downtime?** → `cbmigrate mongo` first; the mongoexport + transform + cbimport pipeline only if you need a transformation it can't express
- **Zero-downtime migration?** → `cbmigrate mongo` for the initial load, then the Debezium MongoDB connector + Couchbase Kafka sink for the delta
- **Want to preserve ObjectId keys?** → use the `%_id%` key template, but consider whether you actually want opaque keys in the target
- **MongoDB Atlas?** → same migration path; `cbmigrate mongo` connects over a standard MongoDB URI, and Atlas change streams feed CDC
- **Need to keep both running for a while?** → dual-write at the app layer + Debezium for backfill; or just Debezium for ongoing sync without app changes
- **Schema audit reveals chaos?** → migration is a great time to clean it up; use a transform step
- **Lots of $lookup joins in current app?** → consider denormalization during migration; reads will be much faster
