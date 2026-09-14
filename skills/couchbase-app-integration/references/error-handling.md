# Error handling — retries, timeouts, transient vs durable

The SDK handles a lot of retry logic for you. The hard part is recognizing what's left for your code to handle, which errors are transient vs durable, and how to set timeouts that match your application's SLA.

> **Verify exception class names against your pinned SDK.** The *categories* below are stable across SDKs; the *spellings* are not. Notably, the CAS-mismatch exception is `CASMismatchException` in the Python SDK but `CasMismatchException` in the JVM SDKs. Look the name up before catching it.

## Contents

- [The two categories of errors](#the-two-categories-of-errors)
- [SDK-level vs application-level retries](#sdk-level-vs-application-level-retries)
- [Setting timeouts](#setting-timeouts)
- [Timeout vs durability tradeoff](#timeout-vs-durability-tradeoff)
- [Retry patterns by use case](#retry-patterns-by-use-case)
- [What a request-cancelled error actually means](#what-a-request-cancelled-error-actually-means)
- [Specific exceptions and what to do](#specific-exceptions-and-what-to-do)
- [Logging and metrics](#logging-and-metrics)
- [Quick decision tree](#quick-decision-tree)

## The two categories of errors

**Transient errors** — the SDK retries them automatically, within the operation's timeout budget:
- Temporary failure — the server is overloaded; back off and retry. (`TemporaryFailException` in Python; `TemporaryFailureException` in the JVM SDKs — verify yours.)
- Request cancellation — the SDK abandoned the request mid-flight
- Network blips — TCP-level disconnects
- Node failovers — the routing target failed, the SDK retries against another node

**Durable errors** — your code must handle them:
- `DocumentNotFoundException` — the doc doesn't exist (your business logic must decide what to do)
- `DocumentExistsException` — INSERT failed because doc already exists
- CAS mismatch — optimistic-concurrency conflict (you read with CAS X, doc was updated by someone else, write with CAS X failed). `CASMismatchException` in Python; `CasMismatchException` in the JVM SDKs
- Authentication failure — credentials wrong
- Bucket / scope / collection not found — config error
- Index not found — query references an index that doesn't exist
- `TimeoutException` — operation didn't complete within budget

### The ambiguity distinction matters more than the transient/durable one

The question your code actually has to answer on a failure is **"did the write apply or not?"** Modern SDKs separate the two timeout cases so you can answer it:

- **Unambiguous timeout** — the request never left in a state where it could have been applied. Safe to retry, idempotent or not.
- **Ambiguous timeout** — the request was sent and the outcome is unknown. Retry only if the operation is idempotent; otherwise reconcile.
- **Durable sync-write ambiguous** (`DurabilitySyncWriteAmbiguousException` in Python) — a durable write whose commit status is unknown. Same handling as an ambiguous timeout.

The JVM SDKs express the first two as `UnambiguousTimeoutException` / `AmbiguousTimeoutException`, both subclasses of `TimeoutException`. Check whether your SDK makes the distinction; if it does, branch on it rather than treating every timeout identically.

## SDK-level vs application-level retries

The SDK retries transient errors automatically. **Don't add application-level retries on top.** This double-retries: SDK already tries N times within the timeout, your wrapper tries M times on top, total tries = N×M with M×timeout total latency.

**When application-level retries ARE appropriate:**

1. **Idempotent operations across timeout boundaries.** If the SDK times out, you don't know if the write succeeded. For idempotent operations (upsert), retrying is safe. For non-idempotent (incrementing a counter), retrying may double-count
2. **CAS mismatches in optimistic-concurrency loops.** Read, modify in memory, write with CAS; on mismatch, re-read and try again. The retry loop is YOUR responsibility, not the SDK's
3. **Circuit-breaker-style backoff for an entire cluster outage.** SDK retries individual operations; your circuit breaker decides "stop hitting the cluster for 30 seconds" if everything is failing

## Setting timeouts

Timeout defaults vary by operation type:

Documented Java SDK defaults ([Java client settings](https://docs.couchbase.com/java-sdk/current/ref/client-settings.html)); other SDKs are broadly aligned but confirm against your own SDK's settings page:

| Operation type | Default timeout | When to override |
|---|---|---|
| KV (get/upsert/etc.) | 2.5 seconds | Lower (e.g., 500ms) for latency-critical paths; higher for warmup scenarios |
| KV durable writes | 10 seconds | Its own setting (`kvDurableTimeout`), separate from plain KV |
| Connect / bootstrap | 10 seconds | Raise on slow or high-latency networks |
| Query (SQL++) | 75 seconds | Set per-query based on expected runtime |
| Analytics | 75 seconds | Set per-query |
| Search | 75 seconds | Per-query |
| Management ops | 75 seconds | Bump for slow management ops |

**Setting at the cluster level** (default for all ops):

```python
# Python SDK 4.x — the class is ClusterTimeoutOptions, passed as `timeout_options`
from couchbase.options import ClusterOptions, ClusterTimeoutOptions

options = ClusterOptions(
    auth,
    timeout_options=ClusterTimeoutOptions(
        kv_timeout=timedelta(seconds=1),
        query_timeout=timedelta(seconds=30),
    ),
)
```

**Setting at the operation level** (overrides cluster default):

```python
result = collection.get("user::42", GetOptions(timeout=timedelta(milliseconds=500)))
```

**Rule of thumb:** set the operation timeout to be roughly the slowest-acceptable response from that operation. Setting it equal to your overall request SLA is fine for KV in a request-response handler; for parallel ops, divide proportionally.

## Timeout vs durability tradeoff

Higher durability levels (waiting for replication/persistence) increase op latency. If you set durability `Majority` AND timeout 500ms AND replicas are catching up after a node failover, your writes may time out.

**Recommendation:** when using a durability level, do not reuse your tight plain-KV timeout. The SDKs already have a *separate, longer* default for durable writes (Java `kvDurableTimeout` = 10s vs `kvTimeout` = 2.5s) precisely because durable writes wait on replication and, for the persist levels, disk. If you override the durable timeout, keep it generous.

## Retry patterns by use case

### Pattern: idempotent write with retry

```python
def upsert_with_retry(coll, key, value, max_attempts=3):
    for attempt in range(max_attempts):
        try:
            return coll.upsert(key, value, UpsertOptions(timeout=timedelta(seconds=2)))
        except TRANSIENT_ERRORS as e:   # tuple of your SDK's timeout + temp-failure types
            if attempt + 1 == max_attempts:
                raise
            time.sleep(0.1 * (2 ** attempt))  # exponential backoff
```

**Use when:** the operation is idempotent (upsert, delete-if-exists). Safe to retry on transient errors after the SDK has already retried within timeout.

### Pattern: CAS-based optimistic concurrency

```python
def increment_counter_safely(coll, key, max_attempts=5):
    for attempt in range(max_attempts):
        try:
            result = coll.get(key)
            new_value = result.content_as[dict]
            new_value["count"] += 1
            coll.replace(key, new_value, ReplaceOptions(cas=result.cas))
            return new_value["count"]
        except CASMismatchException:   # CasMismatchException in the JVM SDKs
            continue  # someone else updated; retry
    raise RuntimeError("Couldn't complete CAS loop after max attempts")
```

**Use when:** atomic read-modify-write on a single document.

**For a pure counter, don't use a CAS loop at all.** Couchbase has server-side atomic counters:

```python
# Python SDK 4.x — binary collection counter ops
from couchbase.options import IncrementOptions
from couchbase.subdocument import SignedInt64, DeltaValue

collection.binary().increment("counter::visits",
                              IncrementOptions(delta=DeltaValue(1),
                                               initial=SignedInt64(0)))
```

There is also a sub-document counter operation (`SD.counter(path, delta)` inside `mutate_in`) for incrementing a numeric field *within* a document. Both are atomic server-side, no loop required ([Python KV operations](https://docs.couchbase.com/python-sdk/current/howtos/kv-operations.html), [Python sub-document operations](https://docs.couchbase.com/python-sdk/current/howtos/subdocument-operations.html)).

### Pattern: circuit breaker

For when an entire cluster is unreachable:

```python
class CouchbaseCircuitBreaker:
    def __init__(self, failure_threshold=10, reset_timeout=30):
        self.failures = 0
        self.opened_at = None
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout

    def call(self, fn, *args, **kwargs):
        if self.opened_at and time.time() - self.opened_at < self.reset_timeout:
            raise CircuitOpenError("Circuit is open")
        try:
            result = fn(*args, **kwargs)
            self.failures = 0
            self.opened_at = None
            return result
        except TRANSIENT_ERRORS as e:   # your SDK's timeout / cancellation types
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.opened_at = time.time()
            raise
```

**Use when:** the cost of waiting on timeouts during a full cluster outage is hurting your service. The circuit breaker fails fast after a threshold of consecutive failures, then probes to see if the cluster recovered.

## What a request-cancelled error actually means

`RequestCanceledException` (JVM SDKs; check your SDK's spelling) means the SDK gave up on this specific request before getting a response. Two scenarios:

1. **Timeout exceeded** — the operation took longer than the budget
2. **SDK shutdown / cluster recovery interrupted the request** — happens during topology changes

For both: **the write may or may not have succeeded on the server.** The SDK doesn't know. Your code must:
- For idempotent ops (upsert, delete): retry is safe
- For non-idempotent ops (insert, counter increment): you have a recoverability problem — either accept it, design the operation idempotently, or use transactions

## Specific exceptions and what to do

Names below are the JVM SDK spellings unless noted; **look up your own SDK's names before catching them.**

| Condition | What it means | Action |
|---|---|---|
| Document not found (`DocumentNotFoundException`) | Doc doesn't exist | Business logic decides — 404? Create? |
| Document exists (`DocumentExistsException`) | INSERT failed | Either expected (idempotent insert workflow) or a race condition |
| CAS mismatch (`CasMismatchException` / Python `CASMismatchException`) | Optimistic concurrency conflict | Re-read, retry the modification |
| Durability impossible (`DurabilityImpossibleException`) | Requested durability can't be met (not enough healthy replicas) | Lower durability or fix the cluster |
| Durable sync-write ambiguous (Python `DurabilitySyncWriteAmbiguousException`) | Durable write's commit status unknown | Treat as ambiguous — retry only if idempotent |
| Bucket / scope / collection not found | Config error | Fix the name in your config |
| Authentication failure | Credentials wrong | Fix the password/cert |
| Temporary failure (Python `TemporaryFailException`) | Server overloaded | SDK retries; if it surfaces to you, the cluster is genuinely stressed |
| Request cancelled (`RequestCanceledException`) | Request gave up before response | Idempotent → retry; non-idempotent → unknown state |
| Ambiguous timeout (`AmbiguousTimeoutException`) | Sent, outcome unknown | Retry only if idempotent |
| Unambiguous timeout (`UnambiguousTimeoutException`) | Never applied | Safe to retry |

## Logging and metrics

Recommended client-side instrumentation:

- Log every error with: operation name, key/query, timeout, exception class, traceback
- Metric: error rate by exception type (separate counters for transient vs durable)
- Metric: operation latency p50/p95/p99 by operation type
- Trace span per Couchbase operation (OpenTelemetry support is built into modern SDKs)

The SDKs emit telemetry; configure your APM (Datadog, New Relic, etc.) to capture it.

## Quick decision tree

- **Error from the SDK?** First check: is it transient or durable? (Transient → SDK has already retried; usually means cluster is stressed)
- **Setting a timeout?** Match it to the operation's expected latency + headroom; don't make it the same as your overall request SLA without thought
- **Need to retry across timeouts?** Only for idempotent operations; otherwise the retry is double-spending
- **Optimistic concurrency on one doc?** CAS loop with `replace` — see pattern above
- **Atomic counter / increment?** Use the binary collection's `increment`/`decrement`, or a sub-document counter op — not a CAS loop
- **Cluster intermittently unavailable?** Circuit breaker on top of the SDK
- **Got a cancellation or ambiguous timeout?** Idempotent op → retry; non-idempotent → accept unknown state or redesign with transactions
- **Unsure of an exception's class name?** Look it up in your SDK's error-handling page. Do not guess — the names differ per SDK and per major version
