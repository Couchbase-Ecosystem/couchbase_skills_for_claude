# Error handling & resilience

Couchbase code fails in specific, recurring ways. Handling them correctly is part of writing the code right the first time, not hardening added later. This reference covers the Couchbase-specific exception taxonomy, retry discipline, idempotency, durability-in-code, and transaction hygiene.

> **Verify exception symbols against the pinned SDK version.** Exception class names and hierarchies differ across SDK generations and languages — the CAS-mismatch type alone is `CASMismatchException` in the Python SDK and `CasMismatchException` in the JVM SDKs. The categories below are stable; the exact type names are not. Check the project's SDK version before catching a specific type, and flag rather than guess.

## Contents

- [The failure categories](#the-failure-categories)
- [Catch narrowly](#catch-narrowly)
- [Retry discipline](#retry-discipline)
- [Idempotency and CAS](#idempotency-and-cas)
- [Durability in code](#durability-in-code)
- [Transactions hygiene](#transactions-hygiene)
- [What to log](#what-to-log)
- [Checklist](#checklist)

## The failure categories

Every Couchbase operation can fail in one of a few ways. Code should handle the ones relevant to the operation, not catch-all:

| Category | Examples | Correct response |
|---|---|---|
| **Not found** | `get` on a missing key | Expected; handle as a normal branch (return `None`/`Optional.empty`), not an exception to log |
| **Transient** | timeout, temporary failure, transient network | Retry with backoff (bounded); it may succeed next time |
| **Ambiguous** | request timed out after send — write may or may not have applied | Retry **only if idempotent**; otherwise reconcile, don't blind-retry |
| **Durable-write ambiguous** | a durable write whose commit status is unknown (Python `DurabilitySyncWriteAmbiguousException`) | Same as ambiguous — reconcile unless idempotent |
| **CAS mismatch** | concurrent modification | Re-read, re-apply, retry the compare-and-swap loop |
| **Durability** | write couldn't meet the requested durability | Surface it; the caller asked for a guarantee that wasn't met |
| **Programmer error** | invalid argument, doc-too-large, unparameterized-query syntax error | Fail loudly — this is a bug, not a runtime condition; don't retry |
| **Auth / permission** | bad credentials, missing RBAC role | Fail fast, surface clearly; retrying won't help |

The critical distinctions: **not-found is not an error** (it's a normal outcome — don't model it as an exception to log-and-alert), and **ambiguous is not the same as transient** (you cannot blindly retry a non-idempotent write that might already have applied).

Several SDKs split the timeout case so your code can tell these apart — the JVM SDKs expose `AmbiguousTimeoutException` and `UnambiguousTimeoutException` as subclasses of `TimeoutException`. **Where your SDK makes that distinction, branch on it**; treating every timeout identically is how non-idempotent writes get double-applied. Where it doesn't, treat every timeout as ambiguous.

## Catch narrowly

```python
# GOOD — distinguishes the outcomes
from couchbase.exceptions import DocumentNotFoundException, CouchbaseException

def load_user(collection, user_id):
    try:
        res = collection.get(user_key(user_id))
        return res.content_as[dict]
    except DocumentNotFoundException:
        return None                      # normal branch, not an error
    except CouchbaseException as e:
        logger.error("user load failed", extra={"user_id": user_id}, exc_info=e)
        raise                            # unexpected — propagate with context
```

- **Catch the specific exception you can handle; let the rest propagate.** A blanket `except Exception: pass` around a Couchbase call hides real failures.
- **Not-found gets its own branch**, above the generic handler.
- **Re-raise with context** (`raise ... from e`) so the trace survives.

## Retry discipline

- **Retry transient errors with bounded exponential backoff + jitter.** Not an unbounded `while True`. Cap attempts and total time; give up and surface after the cap.
- **Don't retry programmer errors or auth failures** — they won't get better, and retrying wastes time and hammers the cluster.
- **The SDK already retries some conditions internally.** Don't wrap every call in your own retry as well without understanding what the SDK does — you can multiply the effective attempts. Layer your retry at the operation/business level, not around every primitive.
- **Prefer the SDK's built-in retry/resilience configuration** where it exists over hand-rolled loops.

## Idempotency and CAS

- **Blind retry is only safe for idempotent operations.** `upsert(key, fullDoc)` is idempotent (same result if applied twice). A counter increment or an append is not — retrying after an ambiguous timeout may double-apply.
- **Use CAS for read-modify-write.** Read the document (capturing its CAS), modify, write back with that CAS; on a CAS-mismatch exception, re-read and retry the loop. This is how you avoid lost updates under concurrency.

```python
# CAS loop — safe concurrent read-modify-write
for _ in range(MAX_CAS_RETRIES):        # bounded, not infinite
    res = collection.get(key)
    doc = res.content_as[dict]
    doc["visits"] += 1
    try:
        collection.replace(key, doc, ReplaceOptions(cas=res.cas))
        break
    except CasMismatchException:
        continue                        # someone else wrote; re-read and retry
else:
    raise RuntimeError("exceeded CAS retries on " + key)
```

- **Prefer server-side atomic ops over CAS loops** when they fit — the server does the atomic change and there is no loop to bound. For a numeric field inside a document, use a sub-document counter op inside `mutate_in` (`SD.counter(path, delta)` in Python). For a standalone counter document, use the binary collection: `collection.binary().increment(key, IncrementOptions(delta=DeltaValue(1), initial=SignedInt64(0)))`. Verify these spellings against your SDK.

## Durability in code

- **Durability is a deliberate per-write decision.** The server documents three levels: `majority` (in memory on a majority of Data Service nodes), `majorityAndPersistActive` and `persistToMajority` ([Durability](https://docs.couchbase.com/server/current/learn/data/durability.html)). The two persistence levels apply to Couchbase buckets only; **Ephemeral buckets support `majority` at most.** All of them cost latency. Use them where a write must survive node failure/failover (financial state, irreversible actions); don't make them the default.
- **Give durable writes their own timeout budget.** The SDKs already do — the Java `kvDurableTimeout` default is 10s against 2.5s for plain KV. Reusing a tight plain-KV timeout for a durable write is a self-inflicted failure.
- **Handle the durability-failure path.** A durability-impossible error (requested durability can't be met because there aren't enough healthy replicas) is a distinct outcome the caller cares about — don't treat it as a generic write success or a swallowed error. Distinguish it from the durable-write-ambiguous case, which is *unknown*, not *failed*.

## Transactions hygiene

When using Couchbase distributed (multi-document ACID) transactions — see the `couchbase-transactions` skill for semantics:

- **Keep transaction lambdas pure and short.** No external side effects (no sending email, no calling other services) inside the transaction body — it may be retried, and side effects would repeat.
- **Let the transaction framework handle its own retries.** Don't wrap your own retry loop around a transaction that already retries internally.
- **Only put in a transaction what needs atomicity.** Transactions cost more than single-document ops; a single-document change doesn't need one (single-doc writes are already atomic).
- **Handle the commit-ambiguous case separately from the failed case.** A transaction-failed error means the transaction did not reach the commit point and was rolled back. A commit-ambiguous error (`TransactionCommitAmbiguous` in the Python SDK) means it **may** have committed — blindly retrying a non-idempotent transaction on that error is a defect. Reconcile instead.
- **Know the documented constraints.** Documents in a transaction must be under **10 MB**, and transactions require **NTP-synchronized clocks** across cluster nodes ([Transactions](https://docs.couchbase.com/server/current/learn/data/transactions.html)).

## What to log

- **Log failures with context, not just the exception.** The key/operation/user involved, so the log line is actionable. `exc_info`/stack trace on unexpected errors.
- **Don't log expected branches.** A not-found that's handled normally shouldn't spam error logs.
- **Never log credentials or full connection strings.** Redact.
- **Log retries at debug/info, exhaustion at error.** A single retry isn't an incident; giving up after the cap is.

## Checklist

- [ ] Not-found handled as a normal branch, not a logged error
- [ ] Exceptions caught narrowly; unexpected ones propagate with context
- [ ] Transient errors retried with bounded backoff+jitter; programmer/auth errors fail fast
- [ ] Ambiguous (timeout-after-send) writes retried only if idempotent; ambiguous/unambiguous branched on where the SDK distinguishes them
- [ ] Read-modify-write uses a bounded CAS loop or subdocument atomic op
- [ ] Durability chosen per-write; durable writes given their own timeout; durability-impossible and durability-ambiguous handled separately
- [ ] Transaction commit-ambiguous handled distinctly from transaction-failed
- [ ] Transaction lambdas pure, short, no side effects, no self-wrapped retry
- [ ] Failures logged with context; secrets redacted; expected branches not spammed
