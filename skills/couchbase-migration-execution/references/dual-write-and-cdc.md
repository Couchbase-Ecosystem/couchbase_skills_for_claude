# Dual-write and CDC

## Contents

- [Dual-write code patterns](#dual-write-code-patterns)
- [Idempotency](#idempotency-in-dual-write)
- [Backfill](#backfill--the-prerequisite)
- [Reconciliation](#reconciliation)
- [CDC operational patterns](#cdc-operational-patterns)
- [Application-side vs CDC](#application-side-vs-cdc-which)
- [Quick decision tree](#quick-decision-tree)

> **Verify SDK and connector symbols against your pinned versions.** Python SDK symbols below are shown in 4.x form; Kafka connector properties are from the current connector documentation.

The two patterns for keeping source and target in sync during a zero-downtime migration. Dual-write is application-driven; CDC is infrastructure-driven. This reference covers code patterns for dual-write and operational patterns for CDC.

## Dual-write code patterns

The app writes to BOTH source and target during the transition. Three variants exist, with different correctness and complexity tradeoffs.

### Variant 1: Best-effort dual-write (source authoritative)

Write to source first; write to target after. If target fails, log it; don't fail the user-facing request.

```python
def update_user(user_id, data):
    # Source is authoritative — must succeed
    source.update_user(user_id, data)
    
    # Target write is best-effort during migration phase
    try:
        couchbase.users.upsert(f"user::{user_id}", data)
    except Exception as e:
        log.warning(f"Dual-write to Couchbase failed for user {user_id}: {e}")
        # Don't raise — source succeeded; reconciliation will catch it
```

**Pros:**
- User experience is unaffected by target failures
- Simple — no transaction logic
- Failure mode: target drifts; reconciliation fixes it

**Cons:**
- Requires a reconciliation process (batch job comparing source and target, fixing drifts)
- Brief windows of divergence between source and target

**Use when:** during early migration phases, when source is still authoritative and you're not yet trusting target.

### Variant 2: Strict dual-write (must succeed on both)

Both writes must succeed; if either fails, raise an error.

```python
def update_user(user_id, data):
    # Source — must succeed
    source.update_user(user_id, data)
    
    # Target — must also succeed
    try:
        couchbase.users.upsert(f"user::{user_id}", data,
                               UpsertOptions(durability=ServerDurability(Durability.MAJORITY)))
    except Exception as e:
        # Now we have a problem — source has the new value, target doesn't
        # Options: rollback source, mark inconsistent and reconcile, fail loudly
        source.rollback_update(user_id)  # if possible
        raise DualWriteFailedException(...)
```

**Pros:**
- Source and target stay in sync (modulo races)
- Higher confidence going into cutover

**Cons:**
- Higher latency (every write hits both systems)
- Failure modes are real: rollback isn't always possible, and a failure means user-facing error
- The "source rollback" step is often the hardest — depending on source DB, it may not be possible without a transaction wrapping both writes

**Use when:** late in migration, when you need high confidence source = target before cutover.

### Variant 3: Outbox pattern (transactional consistency)

Write to source in a transaction that also writes an "outbox" record. A separate process reads the outbox and writes to target.

```python
def update_user(user_id, data):
    with source.transaction() as txn:
        txn.update_user(user_id, data)
        txn.insert_outbox(
            event_type="user_updated",
            target_key=f"user::{user_id}",
            payload=data
        )
        # commits atomically — both rows or neither
    
    # Outbox processor (separate worker)
    # — reads outbox rows
    # — writes to Couchbase
    # — marks outbox row as processed
```

**Pros:**
- Source transaction guarantees the outbox entry; no lost events
- Target writes can be retried independently
- Target writes happen async — no extra latency on user-facing request

**Cons:**
- Most complex pattern
- Need a worker to drain the outbox reliably
- Outbox table grows; needs cleanup

**Use when:** strict consistency required AND your source supports transactions. The most production-robust pattern.

## Idempotency in dual-write

All three variants must be idempotent. Reasons:
- Variant 1: reconciliation may re-apply writes already in target
- Variant 2: rollback + retry can double-write
- Variant 3: outbox processor may re-run an event on restart

**Idempotent write pattern (using upsert with CAS or version):**

```python
def write_to_target(doc_key, data, source_version):
    while True:
        try:
            existing = couchbase.collection.get(doc_key)
            existing_data = existing.content_as[dict]
            if existing_data.get("_source_version", 0) >= source_version:
                # Target already has this version or newer; skip
                return
            # Update with CAS to prevent races
            data["_source_version"] = source_version
            couchbase.collection.replace(doc_key, data, ReplaceOptions(cas=existing.cas))
            return
        except CASMismatchException:   # CasMismatchException in the JVM SDKs
            continue  # another writer beat us; retry
        except DocumentNotFoundException:
            data["_source_version"] = source_version
            couchbase.collection.insert(doc_key, data)
            return
```

The `_source_version` field carries the source's version (for example a row `updated_at` timestamp or an LSN). Target writes are accepted only if they're newer than what's currently there.

**Bound the loop.** As written this retries forever on sustained contention; cap the attempts and surface an error after the cap, as you would any CAS loop.

**An important caveat if the target has XDCR running:** this `_source_version` guard protects against out-of-order writes *from your pipeline*, but XDCR's own conflict resolution operates independently and by different rules. The XDCR default is **sequence-number-based** (more revisions wins), not last-write-wins, and the policy is fixed at bucket creation. If the migration target is also an XDCR endpoint, work out how the two interact before relying on either.

## Backfill — the prerequisite

Dual-write doesn't backfill existing data. If you start dual-writing now, target has only writes from this moment forward. Existing source data isn't there.

**Backfill pattern:**

1. Note a point-in-time T0 (current source max timestamp / sequence number)
2. Start dual-write (variant 1 — best effort, since target is empty)
3. Run a batch job that reads source records older than T0 and writes them to target
4. Once backfill is complete, switch dual-write to variant 2 or 3 (strict)
5. Validate: source row count = target document count

**Order matters:** dual-write must start BEFORE the backfill begins. Otherwise, writes that happen DURING the backfill window are lost — they're not in the backfill (which is a point-in-time snapshot) and not yet in dual-write.

## Reconciliation

Even with strict dual-write, source and target can drift due to:
- Edge cases in error handling
- Manual updates to source bypassing the app
- Bugs in the dual-write code
- Race conditions

**Periodic reconciliation:**

A nightly or weekly batch job that:

1. Reads a sample (or full) set of records from source
2. Reads the corresponding documents from target
3. Compares
4. Logs differences; optionally fixes them

```python
def reconcile_sample(sample_size=10000):
    source_ids = source.get_random_sample_ids(sample_size)
    discrepancies = []
    for sid in source_ids:
        source_doc = source.get(sid)
        try:
            target_doc = couchbase.collection.get(f"user::{sid}").content_as[dict]
        except DocumentNotFoundException:
            discrepancies.append({"id": sid, "issue": "missing_in_target"})
            continue
        
        if not docs_equivalent(source_doc, target_doc):
            discrepancies.append({"id": sid, "issue": "content_mismatch",
                                   "source": source_doc, "target": target_doc})
    return discrepancies
```

`docs_equivalent` is application-specific — it should ignore irrelevant differences (timestamps, system fields) and flag real divergence.

## CDC operational patterns

CDC is "dual-write done by infrastructure instead of application code." The application writes only to source; a CDC pipeline replicates to target.

### Setup with Debezium + Kafka + Couchbase Kafka Connector

The standard open-source CDC stack:

```
[Source DB] → [Debezium connector on Kafka Connect] → [Kafka topics, one per source table]
                                                                  ↓
                                              [Couchbase Kafka sink connector]
                                                                  ↓
                                                            [Couchbase]
```

Each component is its own deployment:
- **Kafka cluster** — at least 3 brokers for production
- **Kafka Connect** — at least 2 nodes for redundancy
- **Debezium connector** — configured as a connector on Kafka Connect
- **Couchbase Kafka Connector** — separate connector on Kafka Connect

**Plan a week minimum** to get this stable in a non-trivial environment.

### Debezium source configuration

Example for Postgres source:

```json
{
  "name": "postgres-source",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "pg-host",
    "database.port": "5432",
    "database.user": "debezium",
    "database.password": "...",
    "database.dbname": "mydb",
    "topic.prefix": "myapp",
    "table.include.list": "public.users,public.orders",
    "plugin.name": "pgoutput"
  }
}
```

This emits events to topics like `myapp.public.users`, `myapp.public.orders`.

### Couchbase Kafka Sink configuration

The property names below are from the current [sink configuration options](https://docs.couchbase.com/kafka-connector/current/sink-configuration-options.html). **Several commonly-cited names are wrong** — it is `couchbase.seed.nodes`, not `couchbase.cluster.address`; `couchbase.document.id`, not `couchbase.document.id.format`; and collection routing is `couchbase.default.collection` (a fully-qualified name), not separate `couchbase.scope` / `couchbase.collection` keys.

```json
{
  "name": "couchbase-sink",
  "config": {
    "connector.class": "com.couchbase.connect.kafka.CouchbaseSinkConnector",
    "topics": "myapp.public.users",
    "couchbase.seed.nodes": "cb.example.com",
    "couchbase.username": "...",
    "couchbase.password": "...",
    "couchbase.bucket": "app_data",
    "couchbase.default.collection": "app_data._default.users",
    "couchbase.document.id": "user::${id}"
  }
}
```

Other properties worth knowing:

| Property | Purpose |
|---|---|
| `couchbase.seed.nodes` | Couchbase Server node addresses |
| `couchbase.bucket` | Target bucket |
| `couchbase.default.collection` | Fully-qualified destination collection |
| `couchbase.document.id` | Format string for the document key |
| `couchbase.remove.document.id` | Whether to strip the ID field from the stored document |
| `couchbase.sink.handler` | Sink handler class; defaults to `com.couchbase.connect.kafka.handler.sink.UpsertSinkHandler` |
| `couchbase.topic.to.collection` | Topic-to-collection mapping — **deprecated**; prefer `couchbase.default.collection` |

Because collection routing is per-connector rather than per-topic, **routing several source tables into several Couchbase collections generally means one sink connector per collection**, not one connector with a comma-separated collection list. Check the current docs for the topic-routing options your connector version supports before designing around a single connector.

The connector's **source** mode is the mirror image — it streams documents out of Couchbase using the **Database Change Protocol (DCP)** and publishes them to Kafka. That's the component you'd use to replicate *out of* Couchbase during a phased cutover, not into it.

### Transformation in CDC

Debezium emits events in a specific format (with `before`, `after`, `op` fields). The sink needs to unwrap these and write Couchbase-shaped documents.

Two transformation places:

**Single Message Transforms (SMTs) in Kafka Connect:**

Light transformations done per-message. Limited expressiveness. Good for: unwrapping Debezium envelope, renaming fields, dropping fields.

**Kafka Streams or ksqlDB:**

Real stream processing. Can do joins, aggregations, complex transformations. Heavier but more capable.

For shape-changing transformations (relational → document with embedding), Kafka Streams is usually necessary.

### CDC failure modes

- **Source connector falls behind** — visible as growing lag in Debezium metrics. Resume after catching up; if too far behind, may need to reset and re-snapshot
- **Sink connector fails** — Kafka retains messages, so it can catch up after restart. But if the failure is permanent (e.g., bad transformation), messages pile up
- **Schema change in source** — Debezium handles most schema changes gracefully but may need connector restart
- **Source DB recreates the table** — Debezium loses its position; needs re-snapshot
- **Kafka topic full** — running out of retention; either lower retention or scale Kafka storage

**Monitor:** connector lag, sink error rate, Kafka topic size. Alert before falling behind too far.

### Initial snapshot strategy

Debezium's initial snapshot reads all existing source data. For very large tables:
- Use `snapshot.mode = exported` to snapshot via a dedicated table
- OR pre-load the target via cbimport before starting CDC
- OR use `snapshot.mode = never` if you've already done a separate bulk load and only want ongoing changes

Don't underestimate snapshot time — for TB-scale tables, snapshot can take days.

### CDC for active-active

Bidirectional CDC (changes flow both ways during migration) is exceptionally hard. Avoid if possible.

If unavoidable:
- Use distinct event IDs per source so the CDC loop can filter out its own emissions
- Implement conflict resolution at the application or pipeline layer
- Accept some inconsistency window

Most active-active migration requirements can be re-shaped as "one direction at a time" with phased cutover. Push hard on whether bidirectional is actually needed before signing up for it.

## Application-side vs CDC: which?

| Aspect | Dual-write | CDC |
|---|---|---|
| App code changes | Yes | No |
| Source code visibility | Required | Not required (uses logs) |
| Setup complexity | Lower (app PR) | Higher (Kafka cluster + connectors) |
| Latency impact | Higher (synchronous writes) | None (async) |
| Transformation flexibility | Maximum (any code) | Limited (SMTs or streams) |
| Failure visibility | Direct (app error) | Indirect (connector metrics) |
| Ops surface during migration | App + reconciliation | Kafka + Connect + connectors |
| Best for | Apps you control, simple transformations | Cannot/won't change source app, simple shape changes |

For most teams that own the source application, dual-write is simpler. For migrations of third-party apps or where you can't deploy app changes, CDC is the answer.

## Quick decision tree

- **Need to keep source and target in sync?** → Dual-write (if you control source app) or CDC (if you don't)
- **Dual-write — which variant?** → Variant 1 (best-effort) early; Variant 2 (strict) late; Variant 3 (outbox) for strict consistency in production
- **Backfilling existing data?** → Start dual-write FIRST, then run the backfill, then validate
- **Need idempotency?** → Yes, always — a `_source_version` field plus a bounded CAS loop. If the target is also an XDCR endpoint, reconcile that with XDCR's own conflict-resolution policy (default: sequence-number-based)
- **Source and target drifting?** → Run periodic reconciliation jobs; expect to fix discrepancies
- **CDC stack?** → Debezium + Kafka + the Couchbase Kafka sink connector for the open-source path. AWS DMS has no first-party Couchbase target — it reaches Couchbase via Kafka or a file staging step, so verify AWS's current target list before designing around it
- **Bulk load before CDC?** → For MongoDB or DynamoDB sources, `cbmigrate` is the fastest way to seed the target; then start CDC for the delta
- **Initial snapshot too slow?** → Skip snapshot, do separate bulk load via cbimport, then start CDC with `snapshot.mode = never`
- **Bidirectional sync needed?** → Reconsider whether you really need this; usually phased one-direction migration is enough
