# Validation and cutover

## Contents

- [Validation philosophy](#validation-philosophy)
- [Count parity](#count-parity)
- [Sample equivalence](#sample-equivalence)
- [Aggregate parity](#aggregate-parity)
- [Application-level testing](#application-level-testing)
- [Continuous diff during dual-write](#continuous-diff-during-dual-write)
- [The cutover](#the-cutover)
- [Cutover monitoring](#cutover-monitoring)
- [Rollback plan](#rollback-plan)
- [Post-cutover validation](#post-cutover-validation)
- [Decommissioning source](#decommissioning-source)
- [Quick decision tree](#quick-decision-tree)

> **Verify SDK symbols against your pinned SDK version** before using any code here.

The two riskiest phases of a migration. Confirming source = target, and switching production traffic. Done well, these are anticlimactic. Done poorly, they're how migrations cause outages.

## Validation philosophy

There's no single "validate the migration" check. Real validation is layered:

1. **Count parity** — same number of items per table/collection
2. **Sample-level equivalence** — pick random records, compare field by field
3. **Aggregate parity** — running known aggregations (sums, counts, averages) on both and comparing
4. **Application-level test** — running the actual app against target, comparing behavior
5. **Continuous diff during dual-write** — comparing source and target in real time as writes happen

Each layer catches different failures:
- Count parity catches "we missed a whole table"
- Sample equivalence catches "transformation is dropping fields"
- Aggregate parity catches "we have all the records but some values are wrong"
- Application-level catches "queries return different results"
- Continuous diff catches drift over time

A robust migration validates at every layer.

## Count parity

The cheapest, simplest check. Just compare counts.

```python
# Source
source_count = source_conn.execute("SELECT count(*) FROM users").fetchone()[0]

# Target — REQUEST_PLUS is mandatory here, see below
from couchbase.n1ql import QueryScanConsistency
from couchbase.options import QueryOptions

result = couchbase_cluster.query(
    "SELECT COUNT(*) AS c FROM `app`.`_default`.`users`",
    QueryOptions(scan_consistency=QueryScanConsistency.REQUEST_PLUS),
)
target_count = next(iter(result.rows()))["c"]

assert source_count == target_count, f"Source={source_count}, Target={target_count}"
```

**The scan consistency is not optional.** A SQL++ query runs against a GSI index, which is updated asynchronously after the KV write. At the default `NOT_BOUNDED`, a count taken shortly after a bulk load will come back **low** — not because documents are missing, but because the index hasn't caught up. That reads as data loss and sends people hunting a bug that doesn't exist. Any query whose purpose is to assert a fact about current state must use `REQUEST_PLUS`.

Note also that `result.rows()` is an iterator in the Python SDK, not a list — consume it rather than subscripting it.

**Catches:** missing records (whole batches), entire collections not migrated.

**Misses:** content errors. Two records with the same key but wrong content still count the same.

For partitioned tables, run count per partition / per shard, not just total. Pinpoints where any drift is.

## Sample equivalence

Pick N random records; fetch from both; compare.

```python
import random

def validate_sample(sample_size=1000):
    # Get N random IDs from source
    source_ids = source.execute(
        f"SELECT id FROM users ORDER BY random() LIMIT {sample_size}"
    ).fetchall()
    
    mismatches = []
    for (sid,) in source_ids:
        source_row = source.execute("SELECT * FROM users WHERE id = %s", sid).fetchone()
        try:
            target_doc = couchbase_collection.get(f"user::{sid}").content_as[dict]
        except DocumentNotFoundException:
            mismatches.append({"id": sid, "type": "missing_in_target"})
            continue
        
        source_doc = transform_row_to_doc(source_row)  # same transformation used in migration
        if source_doc != target_doc:
            mismatches.append({"id": sid, "type": "content_mismatch",
                                "diff": diff(source_doc, target_doc)})
    return mismatches
```

**Sample size** *(estimate — these are practical tiers, not a statistical derivation; if you need a defensible confidence bound, compute the sample size for your population and tolerance)*:

- 100 — quick sanity check
- 1,000 — reasonable confidence for small / medium datasets
- 10,000 — high confidence
- 100,000 — approaching exhaustive for large migrations

Sampling by key is a **KV** operation, not a query — `get` each sampled key directly rather than issuing a SQL++ query per sample. It's a hash lookup with no index dependency and no scan-consistency question.

**`diff` function:** compare maps recursively, optionally ignoring fields you expect to differ (migration timestamps, system fields). Return a list of paths that differ.

## Aggregate parity

Run statistical queries on both sides and compare.

```python
# Source
source_aggregates = source.execute("""
    SELECT
        COUNT(*) AS total,
        SUM(balance) AS total_balance,
        AVG(balance) AS avg_balance,
        MIN(created_at) AS earliest,
        MAX(created_at) AS latest
    FROM accounts
""").fetchone()

# Target — again, REQUEST_PLUS
target_result = couchbase_cluster.query("""
    SELECT
        COUNT(*) AS total,
        SUM(a.balance) AS total_balance,
        AVG(a.balance) AS avg_balance,
        MIN(a.created_at) AS earliest,
        MAX(a.created_at) AS latest
    FROM `app`.`_default`.`accounts` a
""", QueryOptions(scan_consistency=QueryScanConsistency.REQUEST_PLUS))
target_aggregates = next(iter(target_result.rows()))

assert source_aggregates == target_aggregates
```

**Catches:** "we have all the rows but the balances are wrong somewhere." If sums differ by even 1, something is off.

**Per-segment aggregates** are even better:

```sql
SELECT a.tier, COUNT(*) AS n, SUM(a.balance) AS total
FROM `app`.`_default`.`accounts` a
GROUP BY a.tier
```

Comparing per-segment isolates which segment has the drift. Note that aggregates over a whole collection need an index that supports the scan — an unindexed `SELECT COUNT(*)` over a large collection is expensive, and on a big migration target it may hit the query timeout (the Java SDK's documented `queryTimeout` default is 75s). Raise the timeout explicitly for validation queries rather than letting them fail and look like a correctness problem.

## Application-level testing

The most realistic validation: run actual application code against the target and compare its behavior to running against the source.

**Pattern: shadow read mode**

```python
def get_user(user_id):
    # Primary: read from source
    source_user = source.users.find_one({"_id": user_id})
    
    # Shadow: also read from target; compare; log differences
    if SHADOW_READS_ENABLED:
        try:
            target_user = couchbase_users.get(f"user::{user_id}").content_as[dict]
            if not users_equivalent(source_user, target_user):
                log.warning(f"Shadow read mismatch: {user_id}",
                             extra={"source": source_user, "target": target_user})
        except Exception as e:
            log.warning(f"Shadow read failed: {user_id}: {e}")
    
    return source_user
```

Production traffic exercises both systems; you see real-world drift. Don't surface target errors to users; just log.

**Pattern: replay test suite**

If your app has a comprehensive integration test suite, run it twice — once against source, once against target. Diff the responses.

## Continuous diff during dual-write

While dual-write is active, run a continuous comparator:

```python
def continuous_diff(sample_rate=0.01):
    # For sample_rate of all writes, also read back from both and compare
    while True:
        write = next_pending_write_from_log()
        if random.random() < sample_rate:
            source_state = source.read(write.key)
            target_state = couchbase.read(write.key)
            if not equivalent(source_state, target_state):
                alert.send("Dual-write divergence", details={...})
        time.sleep(0.1)
```

A 1% sample rate catches systematic drift while staying lightweight.

## What "equivalent" means

The hard question. Two documents may differ in:

- Timestamp formats (ISO 8601 vs Unix epoch)
- Numeric precision (float vs decimal)
- Field ordering (irrelevant in JSON)
- Missing fields vs null fields (`{}`  vs `{x: null}`)
- Whitespace in string values
- System-added fields (migration timestamps, internal versions)

The migration-defined `equivalent()` function should:
- Normalize both sides to a canonical form
- Ignore fields you expect to differ
- Compare what should be the same

Get this function right — it's the heart of validation.

## When to declare "migration valid"

Tier the confidence:

| Confidence level | Sufficient for |
|---|---|
| Count parity OK | "We migrated everything" |
| Count + small sample equivalence | "Migration is roughly correct" |
| Count + 10K sample + aggregate parity | Staging cutover |
| All above + shadow reads for a week | Production cutover |
| All above + soak period post-cutover | Decommission source |

Don't promote to higher confidence without doing the underlying validation. "We tested 100 records and it was fine" is not "the migration is correct."

## The cutover

Cutover = switching application traffic from source to target. The mechanics depend on how the application is wired:

### Pattern 1: configuration switch

The app reads its data store endpoint from config. Change the config; restart (or reload). Simple but blunt.

```python
# Before
DB_URL = "postgresql://pg-host:5432/mydb"

# After — always couchbases:// (TLS), and mandatory for Capella
DB_URL = "couchbases://cb.example.com"
```

Requires app code to support both DB types via abstraction (or a complete rewrite of data-access code).

### Pattern 2: feature flag

The app's data-access layer reads from one or the other based on a runtime flag. Flip the flag (no restart needed).

```python
def get_user(user_id):
    if feature_flag("use_couchbase"):
        return couchbase_users.get(f"user::{user_id}").content_as[dict]
    else:
        return postgres.execute("SELECT * FROM users WHERE id = %s", user_id).fetchone()
```

Better. The flag can be flipped instantly or gradually (10% of traffic to Couchbase, then 50%, then 100%).

One operational note for the Couchbase side of a cutover: the `Cluster` object must be created **once at application startup** and reused, not per request. A feature-flag rollout that lazily constructs a cluster on first Couchbase-routed request will show a latency spike exactly at the moment you're watching for one. Connect at startup, call the SDK's wait-until-ready before serving, and keep the object for the process lifetime.

### Pattern 3: percentage rollout

Gradually shift traffic:

```python
def get_user(user_id):
    pct = couchbase_traffic_percentage()  # 0-100
    if hash(user_id) % 100 < pct:
        return couchbase_users.get(f"user::{user_id}").content_as[dict]
    else:
        return postgres.execute("SELECT * FROM users WHERE id = %s", user_id).fetchone()
```

Start at 1%, monitor, increase to 10%, monitor, increase to 50%, 100%. Each step is reversible.

### Pattern 4: per-endpoint cutover

For phased migrations, cut over one endpoint at a time:
- `/users/profile` → Couchbase
- `/users/orders` → still source
- `/admin/...` → still source

Lower-stakes endpoints first; high-stakes endpoints last when confidence is highest.

## Cutover monitoring

During and immediately after cutover, watch:

| Metric | Why |
|---|---|
| Application error rate | First sign of "the new path doesn't work" |
| Latency p50 / p95 / p99 | Couchbase typically faster, but transformation overhead could be slower |
| Couchbase cluster health — resident ratio, cache miss rate, memory against the 85% high water mark, KV and query latency | Sudden production load is the cluster's first real stress test. A resident ratio dropping as traffic ramps means the working-set assumption in sizing was wrong |
| Source DB load | Source should now be quiet (or only have dual-writes); if it's still heavy, traffic didn't actually switch |
| User-reported errors / support tickets | The ultimate check |

Set alerts on application error rate spiking; you want to know within minutes if the cutover broke something.

## Rollback plan

Before cutover, document the rollback plan:

**For feature-flag-based cutover:** flip the flag back. Should take seconds.

**For config-switch cutover:** change config back, restart. Takes minutes.

**For percentage rollout:** drop to 0% Couchbase traffic. Seconds.

**Soak period:** keep source running, taking dual-writes from the application, for AT LEAST a week post-cutover. Ideally 2-4 weeks. During soak, rollback is straightforward.

**After soak:** rollback is much harder. Data written to target-only mode isn't in source. You'd need a reverse-direction migration to roll back.

**Decommission source:** only after soak with no incidents. Even then, take a final backup of source before decommissioning, in case of late-discovered issues.

## Common cutover pitfalls

- **No rollback plan documented:** "we'll figure it out if something goes wrong" — works until it doesn't
- **Cutover during peak hours:** schedule for low-traffic windows
- **Cutover with no monitoring set up:** can't tell if it's working
- **Cutover without prior dry-run:** the staging cutover should mirror production exactly
- **Validation counts run at default scan consistency:** they come back low and look like data loss. Use `REQUEST_PLUS`
- **Cluster object created per request in the new code path:** a latency spike at exactly the wrong moment
- **Decommissioning source too quickly:** lose your rollback option
- **Application changes deployed with cutover:** if something breaks, you don't know if it's the code change or the data store change. Deploy app changes separately
- **All traffic at once:** gradual is safer

## Post-cutover validation

For 24-48 hours after cutover:

- Sample-equivalence check between source and target (still both up; source receives writes via the dual-write or CDC pipeline)
- Application error rate monitoring
- Manual spot-checks on key user-facing flows
- Customer support volume — sudden spike means real users hit a bug

If issues emerge: roll back. The first hour is when rollback is cheapest.

## Decommissioning source

After the soak period with no incidents:

1. Stop dual-write or CDC (target is now standalone)
2. Take final backup of source (kept for ~6 months as insurance)
3. Put source in read-only mode for a week (catches anything still relying on it)
4. Shut down source
5. Communicate decommissioning to the team / org
6. Eventually delete the backup once confidence is permanent

Don't skip step 3 — there's almost always *something* still pointing at the source (monitoring scripts, batch jobs, reports). Read-only mode catches them without breaking them.

## Quick decision tree

- **Running a count or aggregate against the target?** → `REQUEST_PLUS` scan consistency, and raise the query timeout. At the default consistency the number will be wrong and will look like data loss
- **Sampling documents for comparison?** → KV `get` by key, not a query per sample
- **Sizing validation effort?** → Count parity is cheap; sample equivalence is hours; a full audit is days. Match it to migration size
- **Sample size?** → 10K random IDs is high confidence for most migrations; 100K for huge ones
- **Cutover mechanism?** → Feature flag (best); config switch (worst, blunt); percentage rollout (incrementally safer)
- **Cutover timing?** → Low-traffic window; never during a holiday weekend or product launch
- **How long is the soak period?** → 2-4 weeks minimum post-cutover before decommissioning source
- **When can you decommission source?** → After 4+ weeks soak with no incidents AND final backup
- **Discovered drift mid-validation?** → Stop. Investigate. Fix the transformation. Re-migrate the affected slice. Re-validate
