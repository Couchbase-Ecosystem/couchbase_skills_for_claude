# Durability and consistency

The two knobs that trade off speed against guarantees. Picking them right is per-operation; the wrong default for both wastes throughput, the wrong default for either creates correctness bugs.

> **Verify SDK symbols against your pinned SDK version.** The *server-side* durability level names below are from Couchbase Server documentation and are stable. The *SDK* enum spellings differ per language and per major version — confirm before writing code.

## Contents

- [Write durability levels](#write-durability-levels)
- [Query consistency levels](#query-consistency-levels)
- [Combining durability + consistency in workflows](#combining-durability--consistency-in-workflows)
- [When durability cannot be met](#when-durability-cannot-be-met)
- [When to skip both](#when-to-skip-both)
- [Quick decision tree](#quick-decision-tree)

## Write durability levels

Couchbase Server documents **three** durability levels; the absence of any level (the default) is a fourth, weaker option. They differ in how many nodes have committed the write before the server acknowledges it ([Durability](https://docs.couchbase.com/server/current/learn/data/durability.html)).

| Level | Acknowledged after | Survives | Bucket types |
|---|---|---|---|
| *(no durability requirement — default)* | Active node's memory | Nothing — not even an active-node restart | Couchbase, Ephemeral |
| `majority` | A majority of Data Service nodes hold the mutation in memory | A node failure | Couchbase, Ephemeral |
| `majorityAndPersistActive` | Majority in memory, **and** the active vBucket's node has synced it to disk | Cluster restart with the active surviving | Couchbase only |
| `persistToMajority` | A majority of Data Service nodes have synced the mutation to disk | Cluster restart, multiple failures | Couchbase only |

**Ephemeral buckets only support levels that do not require persistence** — that is, `majority` only. Asking for a persistence-based level against an Ephemeral bucket is a configuration error, not a slow write.

The "majority" calculation: with replica_count=1 there are 2 copies total (active + 1 replica); majority means both. With replica_count=2 there are 3 copies; majority means 2.

**Latency:** every level above the default adds round-trips and, for the persist levels, disk syncs. The relative ordering in the table is the guarantee ordering and the latency ordering. Absolute numbers depend entirely on your hardware, replica count, and write rate — measure on your own cluster rather than trusting a published figure. Note that the durable-write timeout is its own setting (Java default `kvDurableTimeout` = 10s), separate from the 2.5s plain KV timeout.

### Picking durability — the question to ask

**"What happens if this write is lost?"**

| Loss tolerance | Use |
|---|---|
| Total loss is fine (cache, session, ephemeral state) | no durability requirement |
| Single-node failure shouldn't lose it | `majority` |
| Cluster restart shouldn't lose it (with active surviving) | `majorityAndPersistActive` |
| Multi-failure shouldn't lose it (financial, audit, compliance) | `persistToMajority` |

### Per-operation durability

You pick durability per write, not per app:

```python
# Python SDK 4.x — durability is passed as a ServerDurability wrapping a Durability level
from couchbase.durability import Durability, ServerDurability
from couchbase.options import UpsertOptions

# Cache update — omit durability entirely; fastest path
collection.upsert("cache::user_42", data)

# Normal user data — majority is the right default for most apps
collection.upsert("user::42", user_data,
                  UpsertOptions(durability=ServerDurability(Durability.MAJORITY)))
```

For the persistence-based levels, use the corresponding member of the SDK's durability enum — look up the exact spelling in your SDK's key-value operations page rather than guessing it; the casing is not consistent across SDKs.

### Default — what to use when in doubt

**Use `majority` as your default.** It's a meaningful guarantee (survives single-node failure), it's fast enough for most workloads, and it's the most-commonly-correct choice. It is also the default durability used by Couchbase distributed transactions.

No durability requirement is appropriate only for genuinely-disposable data. `persistToMajority` is for genuinely-irreplaceable data. Most things are in between → `majority`.

### What about replica reads?

Couchbase supports reading from replicas (not just active) via the SDK's get-all-replicas / get-any-replica operations (`get_all_replicas` / `get_any_replica` in Python, `getAllReplicas` / `getAnyReplica` in Java). Replica reads:
- Return stale data if the replica hasn't caught up
- Are useful for "best effort, must respond quickly" scenarios (e.g., during a failover)
- Are NOT useful for normal read patterns — read from active for current data

Important corollary for sizing and throughput planning: **replicas do not serve ordinary reads.** A normal `get` always goes to the active vBucket. Adding replicas buys availability and durability, not read throughput. Skip replica reads unless you have a specific availability reason.

## Query consistency levels

SQL++ queries (N1QL is the legacy name for the same language) hit GSI indexes, which are updated asynchronously after a KV write. The SDKs expose **two** scan-consistency enum members, plus a third, more precise mode reached a different way:

| Mode | What it does | Latency cost |
|---|---|---|
| `NOT_BOUNDED` (default) | Don't wait — return whatever's currently in the index | Fastest |
| `REQUEST_PLUS` | Wait until the index has caught up to the moment the request was made | Slower — may wait during heavy writes |
| "at plus" — `consistent_with` / `consistentWith` with a `MutationState` | Wait only until the index has caught up to *specific* mutations you captured tokens for | Between the two; most precise |

**"At plus" is not an enum member.** In the current SDKs it is expressed by passing a `MutationState` built from the mutation tokens returned by your writes, via the query options' `consistent_with` parameter — not by selecting a `QueryScanConsistency.AT_PLUS` value ([SQL++ queries from the Python SDK](https://docs.couchbase.com/python-sdk/current/howtos/n1ql-queries-with-sdk.html)).

### When each is correct

**`NotBounded`** — appropriate for:
- Dashboards / reports where slight staleness is fine
- High-throughput read paths where ~100ms of staleness doesn't matter
- Most analytical / aggregation queries

**`RequestPlus`** — appropriate for:
- Read-your-own-writes patterns (user updates a record, then immediately re-queries)
- Workflows that depend on the current state being indexed (e.g., "after creating this, find all related records")
- Reconciliation logic

**"at plus" via `consistent_with`** — appropriate for:
- Read-your-own-writes where you have the mutation token from the specific write and don't want to wait for unrelated pending mutations
- Strictly cheaper than `REQUEST_PLUS` under heavy write load, because it waits for less
- Usually `REQUEST_PLUS` is simpler and sufficient

### Per-query consistency

```python
# Python SDK 4.x
from couchbase.n1ql import QueryScanConsistency
from couchbase.options import QueryOptions

# Dashboard query — don't care about freshness
result = cluster.query(
    "SELECT COUNT(*) AS c FROM `app`.`sales`.`orders`",
    QueryOptions(scan_consistency=QueryScanConsistency.NOT_BOUNDED))

# Read-your-own-writes after an insert — always parameterize values
collection.insert("order::ORD-00837", order)
result = cluster.query(
    "SELECT o.* FROM `app`.`sales`.`orders` o WHERE o.customer_id = $cid",
    QueryOptions(scan_consistency=QueryScanConsistency.REQUEST_PLUS,
                 named_parameters={"cid": 42}))
```

### Default — what to use when in doubt

**Use `NOT_BOUNDED` as default; opt into `REQUEST_PLUS` for specific cases.** Most application reads can tolerate < 100ms of staleness, and `NotBounded` is much faster under load.

The trap: defaulting to `REQUEST_PLUS` for everything. This makes queries wait on index catchup, which under heavy write load can mean multi-second waits — destroying throughput.

## Combining durability + consistency in workflows

### Pattern: write, then read your own write

```python
# Write with majority so it's replicated
collection.upsert("user::42", user_data,
                  UpsertOptions(durability=ServerDurability(Durability.MAJORITY)))

# Read with REQUEST_PLUS to ensure the index sees the write
query_result = cluster.query(
    "SELECT u.* FROM `app`.`_default`.`users` u WHERE u.tier = $tier",
    QueryOptions(scan_consistency=QueryScanConsistency.REQUEST_PLUS,
                 named_parameters={"tier": "gold"}))
```

Without `REQUEST_PLUS` (or a `consistent_with` mutation state), the query may return results from before the upsert.

### Pattern: high-throughput ingestion + analytical reads

```python
# Bulk ingest with no durability requirement — speed matters, can re-ingest on loss.
# Prefer a multi-op or bounded concurrency over a naive loop; see performance-patterns.md.
collection.upsert_multi({doc["id"]: doc for doc in batch})
```

Analytical reads run against Capella Analytics or Couchbase Enterprise Analytics through their own SDK/endpoint surface, which has its own consistency options — check that product's docs rather than reusing the query-service enum names.

Both choices favor throughput; appropriate when neither write durability nor read freshness is critical.

### Pattern: financial / audit writes

```python
# persistToMajority + insert (not upsert) for unique-key safety.
# Look up the exact enum member spelling for persistToMajority in your SDK's docs.
collection.insert(f"payment::{payment_id}", payment_data,
                  InsertOptions(durability=ServerDurability(PERSIST_TO_MAJORITY_LEVEL)))
```

Pair with idempotency at the application level: use a unique payment ID generated client-side so retries don't create duplicates.

## When durability cannot be met

If you request `majority` on a cluster that doesn't have enough healthy replicas (for example during a failover with replica_count=1), the SDK raises a durability-impossible error. The exact class name varies by SDK — `DurabilityImpossibleException` in the JVM SDKs; check your SDK's exception list. A related and distinct case is the *sync-write ambiguous* error (`DurabilitySyncWriteAmbiguousException` in Python), which means the durable write may or may not have been applied — treat it as ambiguous, not as a failure.

Options:
- **Catch and downgrade:** retry without a durability requirement and accept the reduced guarantee
- **Catch and surface:** tell the user the write couldn't be made durable; the cluster is in a degraded state
- **Catch and queue for later:** retry when the cluster reports healthy again

Production apps typically need a deliberate policy here — don't just let the exception propagate as a 500 error.

## When to skip both

For ephemeral cache-style writes where neither durability nor consistency matters at all:

```python
collection.upsert(key, value,
                  UpsertOptions(timeout=timedelta(milliseconds=100)))
```

This is the fastest possible write. Pair with the Ephemeral bucket type for the corresponding fast read path — remembering that Ephemeral buckets accept only the `majority` durability level, and that Memcached buckets were removed in Couchbase Server 8.0.

## Quick decision tree

- **Default for writes?** `majority` — meaningful guarantee, manageable latency
- **Cache / session / ephemeral?** No durability requirement (and note Ephemeral buckets support only `majority` anyway)
- **Financial / audit / compliance?** `persistToMajority` (Couchbase buckets only)
- **Default for reads (queries)?** `NOT_BOUNDED` — much faster under load
- **Read-your-own-writes?** `REQUEST_PLUS` on the query, or `consistent_with` a `MutationState` if you have the write's token
- **Cluster degraded, durability impossible?** Catch and decide: downgrade, surface, or queue
- **High-throughput bulk ingest?** `None` + bulk ops; if loss matters, design idempotent ingestion
