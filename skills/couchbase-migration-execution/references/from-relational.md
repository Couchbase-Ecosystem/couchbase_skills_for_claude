# Migrating from relational databases

## Contents

- [Two execution patterns](#two-execution-patterns)
- [Source-specific export](#source-specific-export)
- [Transformation patterns](#transformation-patterns)
- [Handling SQL-specific features](#handling-sql-specific-features)
- [Validation challenges](#validation-challenges-specific-to-relational)
- [CDC for relational sources](#cdc-for-relational-sources)
- [Two execution paths in detail](#two-execution-paths-in-detail)
- [Quick decision tree](#quick-decision-tree)

> **Verify CLI flags and SQL++ function names against the versions you're running.** Source-database export syntax and Couchbase tool flags both change between releases.

PostgreSQL, MySQL, Oracle, SQL Server. The dominant challenge is not the data movement itself; it's the modeling shift from normalized relational tables to document model. This reference covers the execution side; for modeling guidance, see `couchbase-data-modeling`'s `migration-from-relational.md`.

## The fundamental difference from MongoDB migration

MongoDB → Couchbase is shape-preserving. Documents come out as JSON; documents go in as JSON.

Relational → Couchbase is shape-changing. You have rows in tables connected by foreign keys; you need documents that aggregate (or reference) related data based on access patterns.

This means **the transformation step is the bulk of the work** in relational migrations. Bulk loaders matter less; transformation logic matters more.

## Two execution patterns

### Pattern 1: ETL with re-modeling

1. Export each relational table to a flat file (CSV / JSON)
2. Write a transformation program that reads multiple files, joins them in memory or via the new model's logic, produces Couchbase-shaped JSON
3. Bulk load the JSON to Couchbase via `cbimport` — **set `--threads` explicitly; the documented default is 1**

**When to use:** when the new document model differs substantially from the relational tables (denormalization, embedding, restructuring).

**Tooling:** custom Python/Go/Java script for transformation; OR Apache Nifi / Talend / Pentaho if you want a visual ETL designer.

### Pattern 2: CDC with transformation rules

1. Debezium reads the relational DB's transaction log
2. Streaming transformation (Kafka Streams, ksqlDB, or SMTs) reshapes the row-level events into document writes
3. Couchbase Kafka Connector writes to target

**When to use:** when you need ongoing sync (zero-downtime migration), AND the transformation is reasonably simple (row-to-document mostly 1:1, perhaps joining with one related table).

**Trade-off:** CDC handles the data-movement reliably, but complex transformations in the stream are hard. If you need to join 5 tables to make one document, CDC pipelines get awkward fast.

## Source-specific export

### PostgreSQL

**Full export of a table:**

```bash
psql -U postgres -d mydb \
    -c "\copy users TO '/tmp/users.csv' WITH CSV HEADER"
```

**Export to JSON (Postgres 9.2+ has JSON functions):**

```sql
\copy (SELECT row_to_json(t) FROM users t) TO '/tmp/users.jsonl';
```

**Pull related rows for a parent (for transformation):**

```sql
SELECT
    u.id, u.name, u.email,
    array_agg(o ORDER BY o.created_at DESC) AS recent_orders
FROM users u
LEFT JOIN orders o ON o.user_id = u.id
GROUP BY u.id, u.name, u.email;
```

This SQL itself produces a document-shaped result (users with embedded recent orders). Export, dump to JSON lines, cbimport.

### MySQL

**Full export:**

```bash
mysqldump --tab=/tmp mydb users
```

**Export to JSON via SELECT:**

```sql
SELECT JSON_OBJECT('id', id, 'name', name, 'email', email)
FROM users
INTO OUTFILE '/tmp/users.json';
```

MySQL's JSON_OBJECT function lets you shape rows into documents during the export.

### Oracle

**Data Pump export:**

```bash
expdp username/password \
    schemas=myschema \
    directory=DATA_PUMP_DIR \
    dumpfile=mydata.dmp
```

Data Pump exports to Oracle binary format. For Couchbase migration, you'll typically:
1. Use SQL*Plus to export tables to CSV
2. OR use a SQL client (DBeaver, etc.) that can export to JSON

### SQL Server

**bcp (bulk copy) export:**

```bash
bcp "SELECT * FROM mydb.dbo.users" queryout users.csv -c -t, -S server -U user -P password
```

**SSIS** can export to JSON natively for more complex transformations.

## Transformation patterns

Three common shapes for the transformation step:

### Shape 1: Direct row-to-doc

When the table maps cleanly to a collection:

```python
import csv, json

with open('users.csv') as f, open('users.jsonl', 'w') as out:
    reader = csv.DictReader(f)
    for row in reader:
        doc = {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "created_at": row["created_at"]
        }
        out.write(json.dumps(doc) + '\n')
```

Then:

```bash
cbimport json --cluster couchbases://cb.example.com --bucket app_data \
    --format lines --dataset file://$PWD/users.jsonl \
    --scope-collection-exp _default.users \
    --generate-key "user::%id%" --threads 8 --errors-log rejects.log
```

`--errors-log` is worth setting on every migration import: it captures the documents that failed so you can inspect them rather than discovering the gap in a count comparison later. `--limit-docs` and `--skip-docs` let you dry-run a slice of a large file first.

**Use for:** master/reference data, simple lookup tables, anything that's already document-shaped in the schema.

### Shape 2: Join multiple tables into one document

When the target document embeds related data:

```python
import json
from collections import defaultdict

# Read users
users = {}
with open('users.csv') as f:
    for row in csv.DictReader(f):
        users[row["id"]] = {"id": row["id"], "name": row["name"], "addresses": []}

# Read addresses, attach to users
with open('addresses.csv') as f:
    for row in csv.DictReader(f):
        if row["user_id"] in users:
            users[row["user_id"]]["addresses"].append({
                "street": row["street"], "city": row["city"]
            })

# Emit user documents
with open('users_with_addresses.jsonl', 'w') as out:
    for user in users.values():
        out.write(json.dumps(user) + '\n')
```

**Use for:** parent-with-children patterns where the children are bounded (addresses, settings, preferences).

**Caveat:** in-memory join works for moderate data. For TB-scale joins, use a real data engine (Spark, Snowflake, etc.) and emit the results as JSON.

### Shape 3: Multiple tables → multiple collections with references

When children are unbounded (one user has many orders), don't embed all of them — produce separate documents:

```python
# Users — one doc per user, optionally with a recent_orders summary
# Orders — one doc per order, with user_id reference

users = {}
order_counts = defaultdict(int)

with open('users.csv') as f:
    for row in csv.DictReader(f):
        users[row["id"]] = {"id": row["id"], "name": row["name"]}

with open('orders.jsonl', 'w') as out:
    with open('orders.csv') as f:
        for row in csv.DictReader(f):
            doc = {
                "id": row["id"],
                "user_id": row["user_id"],
                "total": float(row["total"])
            }
            out.write(json.dumps(doc) + '\n')
            order_counts[row["user_id"]] += 1

# Add denormalized count to user docs (read-optimization)
for uid, user in users.items():
    user["order_count"] = order_counts.get(uid, 0)

with open('users.jsonl', 'w') as out:
    for user in users.values():
        out.write(json.dumps(user) + '\n')
```

Then load both files into separate collections.

**Use for:** one-to-many relationships where the "many" side is unbounded. Create a secondary index on `user_id` in the orders collection so you can efficiently query "all orders for user X."

## Handling SQL-specific features

### Auto-increment / sequences

Relational DBs auto-generate IDs. Couchbase has no sequence type. Atomic counters exist — the SDK's binary-collection `increment`/`decrement` against a counter document, or a sub-document counter operation within a document — but a single shared counter document is a write hotspot and does not scale as an ID generator.

**Options:**
1. **Keep the existing IDs** — use the relational ID as the Couchbase key suffix: `user::42`, `user::43`. Works fine for read-side compatibility
2. **Switch to ULIDs going forward** — old data keeps numeric IDs, new data gets ULIDs. Document this clearly
3. **Re-key everything to ULIDs** — clean but breaks any external references to old IDs

For most migrations, option 1 is right: keep the IDs to preserve referential integrity from logs, third-party systems, etc.

### Foreign keys

In the target document model, foreign keys become either:
- **Embedded data** — for 1:1 or bounded 1:few relationships
- **Reference fields** — store the foreign key value as a field; query via secondary index

There's no FK enforcement in Couchbase. The application is responsible for referential integrity.

### NULL handling

SQL has NULL as a distinct value; JSON doesn't quite. Three options:

1. **Omit the field entirely** when null in SQL: `if row['email']: doc['email'] = row['email']`
   - Pro: smaller documents, cleaner
   - Con: queries need `IS MISSING` checks
2. **Set to JSON `null`:** `doc['email'] = row['email'] or None`
   - Pro: explicit
   - Con: takes space; field semantics are "we know this is null" vs "we don't have this field"
3. **Use sentinel values:** `doc['email'] = row['email'] or ""`
   - Pro: simpler queries
   - Con: loses the null/missing distinction

Pick one and apply consistently. Option 1 is most idiomatic for Couchbase.

### Stored procedures

SQL stored procedures don't translate directly. Options:
- **Move logic to application code** — most stored procedures are business logic that belongs in services anyway
- **Use Eventing functions** — server-side JavaScript reacting to document mutations (see `couchbase-mcp`). Couchbase Server 8.0 adds an `OnDeploy` handler that runs once at deployment
- **Use SQL++ user-defined functions** — including JavaScript UDFs callable from queries. Verify UDF availability and edition requirements for your server version before designing around them

Migration is a good time to extract proc logic; long-term it should be in code.

### Views

Materialized views or denormalized query helpers in SQL translate to:
- **Materialized summary documents** maintained by Eventing functions
- **SQL++ queries** computed at read time, where the cost is acceptable
- **The Analytics Service** (in-cluster), or **Capella Analytics** / **Couchbase Enterprise Analytics** (separate products), for OLAP-style ad-hoc views. Establish which one is in play — they are different deployments with different sizing

### Triggers

Relational triggers (insert/update hooks) map directly to Couchbase Eventing functions: server-side JavaScript that reacts to document mutations. Same conceptual model, different syntax.

## Validation challenges specific to relational

The trickiest validation: confirming that a multi-table aggregation in SQL gives the same result as a multi-document join in SQL++.

**Approach:**
1. Pick a representative aggregation in the source (for example, "total revenue per customer last month")
2. Run it in SQL on the source
3. Run the equivalent SQL++ on Couchbase — **with `REQUEST_PLUS` scan consistency**, or a freshly-loaded target will report low and look like data loss
4. Compare results

Differences usually mean:
- Modeling didn't capture some relationship correctly (missing FK in the document)
- Edge case in NULL handling
- Date/timestamp format differences
- One side has data the other doesn't (incomplete migration)

## CDC for relational sources

Debezium covers most relational sources well:

| Source | Debezium connector |
|---|---|
| PostgreSQL | `debezium-connector-postgres` — uses logical replication. Requires `wal_level = logical` on the source |
| MySQL | `debezium-connector-mysql` — reads binlog. Requires binlog enabled with `ROW` format |
| Oracle | `debezium-connector-oracle` — uses LogMiner. Extra licensing / setup |
| SQL Server | `debezium-connector-sqlserver` — uses CDC feature. Must be enabled on source DB |

**The transformation challenge in streaming:**

Debezium emits per-row events. If your Couchbase document combines fields from multiple rows (joined data), the CDC pipeline needs to handle that. Options:

1. **Stream-table join in Kafka Streams** — maintain a state store of one table, stream-join the other
2. **Two separate sinks** — load tables individually into Couchbase as separate collections; the application joins at query time
3. **Periodic batch reconciliation** — CDC keeps the basic data in sync; a separate batch job rebuilds aggregated documents periodically

For complex transformations, option 2 (separate collections plus a SQL++ join) is often the right answer despite the runtime cost. Note that the Couchbase Kafka sink connector routes to a collection per connector (`couchbase.default.collection`), so "separate sinks" is usually literal: one sink connector per target collection.

## Two execution paths in detail

### Path A: Big-bang with ETL

```
[Postgres] --pg_dump--> [CSV/JSON files] --transform-->  [docs.jsonl]  --cbimport--> [Couchbase]
                                                                                          ^
                                                            [Validation queries] ---------+
```

**Timeline:** weeks for moderate scale *(estimate)*. The transform step is where the time goes.

### Path B: CDC with eventual model alignment

```
[Postgres] --Debezium--> [Kafka topics, one per table] --> [Couchbase Kafka Connector] --> [Couchbase]
                                                                                              ^
                                                            [Eventing functions to aggregate] +
```

**Timeline:** weeks for tooling setup *(estimate)*, then ongoing. The Eventing functions emit aggregated documents based on individual row events.

## Quick decision tree

- **One-shot migration, modest scale, modeling change required?** → ETL: pg_dump/mysqldump + transformation script + cbimport
- **Zero-downtime, simple row-to-doc shape?** → Debezium + Couchbase Kafka Connector
- **Zero-downtime, complex aggregation needed?** → Debezium + Eventing functions for aggregation (or batch reconciliation)
- **Large scale, Spark already available?** → Spark migration: read JDBC, transform, write Couchbase via Spark Connector
- **Source has complex stored procedures?** → Extract business logic to app code before migrating (migration is a good catalyst for this work)
- **NULL handling?** → Omit fields when null (idiomatic Couchbase); use `IS MISSING` in queries. Note SQL++ distinguishes `MISSING` from `NULL`, which is exactly the distinction option 1 relies on
- **Validating aggregates against the target?** → `REQUEST_PLUS` scan consistency, or the numbers will be wrong
- **Foreign keys?** → Embed when bounded; reference + secondary index when unbounded
- **Sequences / auto-increment IDs?** → Keep them for backwards compatibility; switch to ULIDs for new data going forward
