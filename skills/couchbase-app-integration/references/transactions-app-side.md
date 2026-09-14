# Transactions — application side

Couchbase Distributed ACID Transactions provide atomicity across multiple documents. In current SDK generations the transactions API is built into the SDK rather than being a separate dependency. This reference covers when to use them, the patterns, and the gotchas.

> **Verify SDK symbols against your pinned SDK version.** The transactions API surface has changed across SDK generations. Couchbase documents distributed transactions for the **C++, .NET, Go, Java, Kotlin, Node.js, PHP, Python and Scala** SDKs ([Transactions](https://docs.couchbase.com/server/current/learn/data/transactions.html)); if your SDK isn't on that list, check its own docs before promising the feature.

## Contents

- [When transactions are the right answer](#when-transactions-are-the-right-answer)
- [How they work, briefly](#how-they-work-briefly)
- [Code pattern — Python](#code-pattern--python)
- [Code pattern — Java](#code-pattern--java)
- [Operations supported inside transactions](#operations-supported-inside-transactions)
- [Retry behavior](#retry-behavior)
- [Failure modes](#failure-modes)
- [Durability inside transactions](#durability-inside-transactions)
- [Performance characteristics](#performance-characteristics)
- [Anti-patterns](#anti-patterns)
- [When NOT to use transactions](#when-not-to-use-transactions)
- [Quick decision tree](#quick-decision-tree)

## When transactions are the right answer

Couchbase has three concurrency tools, in increasing order of cost and capability:

| Tool | Scope | Use when |
|---|---|---|
| Single-document KV write | One document | Atomic update of a single doc; most operations |
| Subdocument ops (`mutate_in`) | One document, multiple fields | Atomic update of multiple fields of one doc |
| Distributed Transactions | Multiple documents | Atomicity required across docs |

Reach for transactions only when atomicity genuinely matters across documents — typically:
- Financial transfers (debit one account, credit another)
- Multi-step workflows where partial completion is a bug
- Document references that must stay consistent (create parent + first child)
- Inventory adjustments tied to order placement

Don't reach for transactions when:
- A single doc's worth of state would suffice (use subdoc instead)
- Eventual consistency is OK (use independent writes + reconciliation)
- The "transaction" is really a workflow with retry logic baked in (often simpler)

Transactions cost more than equivalent non-transactional KV operations — Couchbase's own documentation notes that "transactional updates may be less performant than non-transactional updates." The size of that gap depends on your cluster, document count per transaction and durability level; measure it rather than assuming a multiplier.

**Documented constraints:**
- Documents involved in a transaction must be **less than 10 MB** in size
- Transactions require **NTP-synchronized clocks** across all cluster nodes
- For query-based mutations, Couchbase recommends limiting the number of mutations within a single transaction

## How they work, briefly

Couchbase transactions use a two-phase commit protocol:

1. **Begin** — transaction context created
2. **Operations phase** — reads and writes recorded but not visible to others
3. **Commit** — writes become visible atomically across all affected documents
4. **OR Rollback** — if commit fails or app calls rollback, all changes discarded

The mechanism uses Active Transaction Records (ATRs) — special docs that track in-flight transactions, allowing recovery if a client crashes mid-transaction.

## Code pattern — Python

```python
# Python SDK 4.x
def transfer_funds(cluster, accounts_coll, from_account_id, to_account_id, amount):
    def transaction_logic(ctx):
        from_doc = ctx.get(accounts_coll, f"account::{from_account_id}")
        to_doc = ctx.get(accounts_coll, f"account::{to_account_id}")

        from_content = from_doc.content_as[dict]
        to_content = to_doc.content_as[dict]

        if from_content["balance"] < amount:
            raise InsufficientFundsException()

        from_content["balance"] -= amount
        to_content["balance"] += amount

        ctx.replace(from_doc, from_content)
        ctx.replace(to_doc, to_content)

    result = cluster.transactions.run(transaction_logic)
    return result
```

The `transaction_logic` callable receives an attempt context (`ctx`) and runs inside the transaction. The SDK handles begin, commit, rollback, and retry on conflict.

## Code pattern — Java

```java
// Java SDK 3.x
TransactionResult result = cluster.transactions().run(ctx -> {
    TransactionGetResult fromDoc = ctx.get(accountsCollection, "account::" + fromId);
    TransactionGetResult toDoc = ctx.get(accountsCollection, "account::" + toId);

    JsonObject from = fromDoc.contentAsObject();
    JsonObject to = toDoc.contentAsObject();

    if (from.getDouble("balance") < amount) {
        throw new InsufficientFundsException();
    }

    from.put("balance", from.getDouble("balance") - amount);
    to.put("balance", to.getDouble("balance") + amount);

    ctx.replace(fromDoc, from);
    ctx.replace(toDoc, to);
});
```

Same pattern. The transactions API is built into the SDK in recent versions.

## Operations supported inside transactions

- `ctx.get(collection, id)` — read; returns a transactional get result
- `ctx.insert(collection, id, content)` — create new doc
- `ctx.replace(doc, content)` — update existing (requires a prior `ctx.get`)
- `ctx.remove(doc)` — delete (requires a prior `ctx.get`)
- `ctx.query(statement, options)` — SQL++ inside the transaction (joins, multi-doc updates)

Not supported inside transactions:
- KV operations directly on the collection (`collection.upsert(...)`) — only via `ctx.*`
- Most admin operations
- Sub-document operations — the transaction context documents only the CRUD and query operations above; use `ctx.replace` with the full content instead

## Retry behavior

Transactions automatically retry on conflict (two transactions touching the same docs). The library uses backoff to avoid livelock.

**Implication:** your transaction logic may run multiple times. Make it idempotent — don't have side effects (logging, calling external services, modifying app state) inside the lambda that you wouldn't want to happen multiple times.

```python
# BAD — sends email N times on retry
def transaction_logic(ctx):
    doc = ctx.get(coll, "order::42")
    ctx.replace(doc, modified)
    send_confirmation_email(...)  # ← side effect inside lambda

# GOOD — side effect after commit
def transaction_logic(ctx):
    doc = ctx.get(coll, "order::42")
    ctx.replace(doc, modified)

result = cluster.transactions.run(transaction_logic)
if result.committed:
    send_confirmation_email(...)
```

## Failure modes

**Transaction commit succeeded:** the run returns a transaction result. All changes are visible.

**Transaction did not reach the commit point:** the SDK raises a transaction-failed error (`TransactionFailed` in the Python SDK; check your SDK for its spelling). All changes are rolled back. Your code decides what to do — retry the whole transaction, fail the request, etc.

**Transaction possibly committed:** the SDK raises a commit-ambiguous error (`TransactionCommitAmbiguous` in the Python SDK). This is the genuinely hard case — you do **not** know whether the transaction committed. Do not blindly retry a non-idempotent transaction on this error; reconcile the affected documents instead.

**Application code threw exception inside transaction:** rolled back. Exception propagates to your caller.

**Client crashed mid-transaction:** the transaction is marked as in-flight in the ATR. Other clients reading the affected docs see the pre-transaction state. The transaction times out and is cleaned up by the next client to encounter it.

**Cluster lost replicas mid-transaction:** the library handles this; transaction may take longer but typically completes.

## Durability inside transactions

Transactions can request a durability level for their commits:

**The documented default is `majority`** — "the default configuration will perform all writes with the durability setting `Majority`." That is the right choice for most workloads. Durability can be raised cluster-wide via the SDK's transactions configuration at connect time (in the Python SDK, a `TransactionConfig` carrying a `ServerDurability(...)`), and per-transaction options exist in some SDKs — check your SDK's transactions page for the exact option class and field names before writing the code.

Higher durability means slower commits. For financial workloads `persistToMajority` is appropriate.

## Performance characteristics

The overhead is in the two-phase commit protocol — ATR writes, staging, and the commit phase — and is largely **fixed per transaction** rather than per document.

**Practical implication:** prefer batching multi-doc work into one transaction over many small transactions. Measure the actual cost on your own cluster; absolute latency depends on durability level, replica count, document sizes and hardware, so no published figure will transfer.

## Anti-patterns

- **Using transactions for single-doc operations** — overhead with no benefit. Use direct KV.
- **Side effects inside the transaction lambda** — runs multiple times on retry
- **Long-running transactions** — keep them short; a transaction that stays open holds staged state and is more likely to conflict or expire
- **Reading many docs that don't need modification** — pulls them into the transaction's scope. Read outside, modify inside
- **Very large transactions** — Couchbase recommends limiting the number of mutations in a transaction, particularly for query-based mutations. Split into smaller transactions where the atomicity boundary allows
- **Documents at or above 10 MB** — the documented transaction limit is under 10 MB per document
- **Clusters without NTP** — transactions require synchronized clocks across cluster nodes

## When NOT to use transactions

Two patterns where transactions look tempting but aren't the best answer:

### Pattern 1: idempotent workflow

```
1. Reserve inventory
2. Charge card
3. Create order document
4. Send confirmation
```

This LOOKS like it needs a transaction. But it's actually better modeled as an idempotent state machine:

- Each step writes a state doc indicating progress
- On retry / failure, the next attempt picks up where the last left off
- Reservations and charges are themselves idempotent (use idempotency keys)
- No multi-doc atomicity needed; just resumability

Workflow engines (Temporal, Step Functions, custom) often suit this better than transactions.

### Pattern 2: eventually-consistent aggregation

```
Order created → user's "total_orders" counter should go up
```

Don't do this in a transaction. Two patterns work better:
- Eventing function reacts to order creation, updates user counter (eventually consistent)
- Compute the counter on read via a SQL++ aggregation (always consistent, slower reads)
- Materialized counter doc updated by a background job (eventually consistent, fast reads)

A transaction here would force the order-creation path to also update the user doc, coupling the two writes and slowing the hot path.

## Quick decision tree

- **Single doc atomic update?** → KV upsert / replace, no transaction
- **Multiple fields of one doc?** → `mutate_in`, no transaction
- **Multi-doc atomicity required?** → Transaction
- **Multi-doc but eventual consistency OK?** → Independent writes, reconcile if needed
- **Workflow with steps + idempotency?** → State machine pattern, not transaction
- **Cross-service atomicity (Couchbase + Stripe + email)?** → Saga pattern, not transaction
- **Inside a transaction, want a side effect?** → Defer it until after commit
- **Got a commit-ambiguous error?** → Do not blindly retry; reconcile the affected documents
- **Unsure of the transactions API shape in your SDK?** → Check that SDK's distributed-transactions page; the surface differs across SDKs and versions
