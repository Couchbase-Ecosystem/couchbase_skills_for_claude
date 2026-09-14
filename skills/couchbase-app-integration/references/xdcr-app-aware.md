# XDCR-aware application patterns

Cross-Datacenter Replication runs at the server level, but its existence shapes how your application code should handle writes, conflicts, and reads. This reference covers the patterns your client code needs when XDCR is in play.

> **Verify SDK symbols against your pinned SDK version** before using any code here.

## Contents

- [The two XDCR shapes](#the-two-xdcr-shapes)
- [Active-passive patterns](#active-passive-patterns)
- [Active-active patterns](#active-active-patterns)
- [Conflict logging (Couchbase Server 8.0+)](#conflict-logging-couchbase-server-80)
- [Idempotency keys](#idempotency-keys)
- [When NOT to use active-active](#when-not-to-use-active-active)
- [Reading replicated data — what to expect](#reading-replicated-data--what-to-expect)
- [Monitoring application-relevant XDCR metrics](#monitoring-application-relevant-xdcr-metrics)
- [Quick decision tree](#quick-decision-tree)

## The two XDCR shapes

**Active-passive:** writes go to one source cluster; replication flows one-way to one or more target clusters. Targets are read-only from the application's perspective.

**Active-active:** writes can go to either cluster; replication flows bidirectionally. Same document can be written in both clusters; conflict resolution decides which version wins.

The application code differs significantly between these two shapes.

## Active-passive patterns

The simple case. Your application has:

- A write cluster (source)
- One or more read clusters (replicas, in other regions)

### Pattern: regional reads, central writes

```python
class CouchbaseService:
    def __init__(self):
        self.write_cluster = Cluster("couchbases://write.example.com", ...)
        self.read_cluster = Cluster(f"couchbases://read-{my_region}.example.com", ...)

    def get_user(self, user_id):
        # Read from local cluster — fast
        return self.read_cluster.bucket("users").collection("users").get(f"user::{user_id}")

    def update_user(self, user_id, data):
        # Write to central cluster — replicated to local
        return self.write_cluster.bucket("users").collection("users").upsert(f"user::{user_id}", data)
```

**Tradeoff:** writes have higher latency (cross-region to write cluster). Reads are local. The right answer when read-heavy.

### Pattern: read-your-own-writes across regions

The challenge with the previous pattern: after writing to the write cluster, the local read cluster hasn't received the replication yet. Reading immediately may return the old value.

Three approaches:

**A. Read from write cluster for known-recent reads:**

```python
def update_and_get(self, user_id, data):
    self.write_cluster... .upsert(...)
    # Read back from write cluster so we see our own write
    return self.write_cluster... .get(...)
```

Simple but pays write-cluster latency for the read.

**B. Cache the write locally:**

```python
def update_user(self, user_id, data):
    self.write_cluster... .upsert(...)
    self.local_cache[user_id] = data

def get_user(self, user_id):
    if user_id in self.local_cache:
        return self.local_cache.pop(user_id)
    return self.read_cluster... .get(...)
```

Avoids the cross-region latency. Cache must be sized for write rate × replication lag.

**C. Use XDCR lag estimate and wait:**

```python
def update_and_get(self, user_id, data):
    self.write_cluster... .upsert(...)
    time.sleep(estimated_xdcr_lag_seconds)
    return self.read_cluster... .get(...)
```

Janky. Don't do this except for dev / debugging.

### Pattern: failover to alternate cluster

If your local read cluster becomes unreachable, fall back to another region:

```python
def get_user(self, user_id):
    try:
        return self.local_cluster... .get(f"user::{user_id}",
                                          GetOptions(timeout=timedelta(milliseconds=500)))
    except (TimeoutException, NetworkException):
        return self.fallback_cluster... .get(f"user::{user_id}")
```

The fallback adds latency but keeps you alive during regional outages.

## Active-active patterns

The harder case. Both clusters accept writes; conflicts are inevitable when the same document is updated in both within the replication window.

### Conflict resolution at the server

XDCR has built-in conflict resolution, and **the default is not last-write-wins.** Couchbase documents two policies, chosen when the bucket is created ([XDCR conflict resolution](https://docs.couchbase.com/server/current/learn/clusters-and-availability/xdcr-conflict-resolution.html)):

| Policy | How it decides | Tiebreakers |
|---|---|---|
| **Sequence number-based** (the **default** if you don't choose) | Compares document *revision counts* — the version that has been updated more times wins | CAS value, then expiration, then document flags |
| **Timestamp-based (last write wins, LWW)** | Compares the document timestamp stored in the CAS; the most recent update wins | Sequence number, then expiration, then document flags |

Two consequences your application design has to account for:

1. **"More updates" is not "more recent."** Under the default sequence-number policy, a document updated five times in cluster A beats a single, later update in cluster B. If your semantics are genuinely "newest wins," you must select the timestamp-based policy explicitly at bucket creation.
2. **Timestamp-based resolution requires synchronized clocks** across every node in every participating cluster. The docs are explicit: "if clocks are not so synchronized, conflict resolution may produce unexpected results." Run NTP.

The conflict-resolution policy is chosen at bucket creation. Treat it as an architectural decision made before the first write, not a tunable.

Either way, conflict resolution means one side's write is discarded. Plan for that.

### Application-side patterns for active-active

**Pattern: design for the cluster's conflict-resolution policy**

If your data semantics work with whichever policy the bucket was created with (verify which — sequence-number is the default):
- User profile updates (each update fully replaces — latest is correct)
- Settings / preferences
- Cache entries

No application-side code needed. The cluster's default resolution does the right thing.

**Pattern: idempotent operations with versioning**

For data where "merge" matters more than "overwrite":

```json
{
  "id": "user::42",
  "_v": 7,                      // version, incremented per logical update
  "_updated_regions": ["us", "eu"],  // regions that touched this version
  "data": {...}
}
```

Application code:
1. Read the doc with CAS
2. Check the version — if a newer version exists in your region, use it
3. Compose a merge — combine fields from both versions according to merge rules
4. Write back with incremented version

This is application-level conflict resolution. Heavier but lets you avoid losses.

**Pattern: append-only event sourcing**

Instead of mutating documents, append events:

```
event::user_42::01HXK7M8YQNT9N5J2VCABCDE  { type: "name_change", value: "Alice", ts: "..." }
event::user_42::01HXK7M8YQNT9N5J2WCFGHIJK  { type: "email_change", value: "alice@new", ts: "..." }
```

Both clusters can write events independently — no conflict possible because the keys are unique (ULID).
Read-side computes current state by replaying events.

Application code is more complex but conflicts go away entirely.

**Pattern: per-region key prefixes**

Each region writes to its own key namespace; aggregation happens at read time:

```
user::42::region:us    { fields written from US cluster }
user::42::region:eu    { fields written from EU cluster }
```

Writes never conflict. Reads fetch both regional docs and merge.

Use when fields are clearly region-owned (e.g., user's US-shipping-address vs EU-shipping-address).

### Mutation tokens for read-your-own-writes

Couchbase SDKs return a mutation token from writes. Collecting tokens into a `MutationState` and passing it as the query's `consistent_with` option makes the query wait only for *those* mutations to be indexed — the "at plus" mode. Mutation tokens must be enabled on the SDK (the Java default `mutationTokensEnabled` is `true`).

```python
# Python SDK 4.x — shape of the pattern; confirm the MutationState construction
# helper's exact name against your SDK's docs before using it.
result = collection.upsert("user::42", data)

query_result = cluster.query(
    "SELECT u.* FROM `app`.`_default`.`users` u WHERE u.tier = $tier",
    QueryOptions(named_parameters={"tier": "gold"},
                 consistent_with=mutation_state_from(result)))
```

This is the same idea as `REQUEST_PLUS` but more precise — it waits only for THIS write to be indexed, not "everything pending."

In XDCR context: the mutation token tells you "your write reached this cluster," but it says nothing about other clusters. For cross-cluster read-your-own-writes, you still need one of the patterns above.

## Conflict logging (Couchbase Server 8.0+)

**XDCR Conflict Logging is new in 8.0** — "detailed logging of concurrent conflicts during Active-Active replication" ([What's New in 8.0](https://docs.couchbase.com/server/current/introduction/whats-new.html)). On 7.x clusters this surface does not exist; you infer conflict rates from application-side comparison instead.

From the application side:

- Application code typically doesn't read the conflict log directly — it's an audit / debugging surface
- Operators read it through the cluster's management surface; the `couchbase-mcp` skill covers that tooling
- Useful for understanding the magnitude of conflicts in production

8.0 also adds an **Incoming Replications** view, giving visibility into replication streams arriving from remote clusters.

If your application is hitting many conflicts (visible in the log), reconsider whether active-active is the right shape. Active-passive may give you what you actually want with much less complexity.

## Idempotency keys

For active-active or any retried workflow, idempotency keys are essential:

```python
def create_order(user_id, items, idempotency_key):
    # Check if this idempotency key was already used
    try:
        existing = collection.get(f"idemp::{idempotency_key}")
        return existing.content_as[dict]["order_id"]
    except DocumentNotFoundException:
        pass

    order_id = generate_order_id()
    collection.insert(f"order::{order_id}", order_data)
    collection.insert(f"idemp::{idempotency_key}",
                       {"order_id": order_id},
                       InsertOptions(expiry=timedelta(days=30)))
    return order_id
```

The idempotency document acts as a guard against double-creation when the client retries or replicates.

## When NOT to use active-active

The honest answer: active-active is hard, and you should avoid it unless you have a specific reason:

**Avoid active-active when:**
- The data is naturally regional (US users access US data, EU users access EU data) — partition the data instead
- Reads-from-anywhere is the goal — active-passive with read replicas gives you this with less complexity
- Conflicts would be expensive — financial systems, inventory, counters

**Use active-active when:**
- Users actually travel between regions and write from wherever they are
- The data is genuinely shared globally and writes can come from anywhere
- You've accepted the conflict-resolution model (and verified it's correct for your data)
- You've measured the conflict rate and it's low enough to tolerate

## Reading replicated data — what to expect

Even in active-passive, the target cluster's view of a write lags behind the source. Application code reading from the target should:

- Tolerate "the data isn't there yet" for short windows (seconds typically)
- Not assume that two writes in the source appear in the target in the same order (XDCR doesn't strictly preserve order across documents)
- Handle the case where a delete on the source hasn't reached the target yet

## Monitoring application-relevant XDCR metrics

Your app should be aware of XDCR health, even if it doesn't manage XDCR directly:

- **`changes_left`** — pending replication backlog; a growing trend is a problem
- **Replication lag / age of last replicated data** — how stale the target is; alert if it exceeds your expected lag. Check the exact stat names against your cluster's XDCR statistics reference
- **Conflict log entries** (8.0+) — if you're using active-active, watch the conflict rate

Wire these into your application's observability so you can correlate "users seeing stale data" with "XDCR is behind."

## Quick decision tree

- **Single-region writes + multi-region reads?** → Active-passive, read locally, write to central; cache local-writes briefly if needed
- **Need writes-from-anywhere?** → Active-active, but pick a conflict-resolution model first
- **Data is naturally regional?** → Partition by region; don't do active-active
- **Need atomicity across clusters?** → You don't get it. Design around it (eventual consistency, idempotency)
- **Read-your-own-writes within one cluster?** → Mutation token + `consistent_with` on the query (or `REQUEST_PLUS` if you don't have the token)
- **Which conflict-resolution policy?** → Sequence-number is the default; choose timestamp/LWW at bucket creation if "newest wins" is your actual semantic — and run NTP if you do
- **Read-your-own-writes across clusters?** → Read from the cluster you wrote to, or cache locally
- **Conflicts hurting you?** → Reconsider whether active-active is the right shape; maybe active-passive + region partitioning is correct
