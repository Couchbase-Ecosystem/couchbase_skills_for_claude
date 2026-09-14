# Transaction patterns

## Contents

- [The lambda shape](#the-lambda-shape)
- [Python](#python)
- [Java](#java)
- [Node.js](#nodejs)
- [Error handling](#error-handling)
- [The idempotency key pattern](#the-idempotency-key-pattern)
- [SQL++ transactions](#sql-transactions)
- [Single query (implicit) transactions](#single-query-implicit-transactions)
- [Savepoints](#savepoints)
- [Configuration](#configuration)

## The lambda shape

Every SDK follows the same shape: you supply the logic — including conditionals — in a lambda, and the transactions API drives commit, rollback, and retry. On a transient error such as a write conflict, the API rolls back what it has done and runs the lambda again. The application does not implement the retry loop.

A transaction begins when the SDK's `run` is called, when `BEGIN TRANSACTION` is executed, or when a single query transaction is issued. It ends on an explicit commit, an explicit rollback, the lambda completing successfully (an implicit commit), an unresolvable application error (an automatic rollback), or expiry (a rollback).

Because the lambda may run more than once, **generate ids and timestamps inside it**, never outside.

Exact method names and types vary by SDK version; check the SDK's own "Distributed ACID Transactions" page for the release you are on.

## Python

```python
def transfer_funds(cluster, from_id, to_id, amount):
    accounts = cluster.bucket("bank").scope("_default").collection("accounts")

    def txn_logic(ctx):
        from_doc = ctx.get(accounts, from_id)
        to_doc = ctx.get(accounts, to_id)

        from_data = from_doc.content_as[dict]
        to_data = to_doc.content_as[dict]

        if from_data["balance"] < amount:
            raise ValueError(f"Insufficient funds: {from_data['balance']} < {amount}")

        from_data["balance"] -= amount
        to_data["balance"] += amount

        ctx.replace(from_doc, from_data)
        ctx.replace(to_doc, to_data)

    return cluster.transactions.run(txn_logic)
```

Raising from inside the lambda for a business-rule violation is the intended way to abort: the transaction rolls back and the error surfaces to the caller.

## Java

```java
TransactionResult result = cluster.transactions().run(ctx -> {
    TransactionGetResult fromDoc = ctx.get(accounts, "account::" + fromId);
    TransactionGetResult toDoc   = ctx.get(accounts, "account::" + toId);

    JsonObject from = fromDoc.contentAsObject();
    JsonObject to   = toDoc.contentAsObject();

    double balance = from.getDouble("balance");
    if (balance < amount) {
        throw new InsufficientFundsException("Balance " + balance + " < " + amount);
    }

    from.put("balance", balance - amount);
    to.put("balance", to.getDouble("balance") + amount);

    ctx.replace(fromDoc, from);
    ctx.replace(toDoc, to);
    // ctx.commit() is optional — completing the lambda commits implicitly
});
```

KV and Query can be mixed freely in the same transaction:

```java
cluster.transactions().run(ctx -> {
    QueryResult qr = ctx.query(inventory,
        "UPDATE hotel SET price = $1 WHERE name = $2",
        TransactionQueryOptions.queryOptions()
            .parameters(JsonArray.from("from £89", "Glasgow Grand Central")));
});
```

Be aware that once a query runs, the transaction is in **query mode** and subsequent KV operations execute with the user's *query* permissions. See `mechanics.md`.

## Node.js

```javascript
const result = await cluster.transactions().run(async (ctx) => {
    const fromDoc = await ctx.get(accounts, `account::${fromId}`);
    const toDoc   = await ctx.get(accounts, `account::${toId}`);

    const from = fromDoc.content;
    const to   = toDoc.content;

    if (from.balance < amount) {
        throw new Error("Insufficient funds");
    }

    from.balance -= amount;
    to.balance   += amount;

    await ctx.replace(fromDoc, from);
    await ctx.replace(toDoc, to);
});
```

## Error handling

Three outcomes need distinct handling. Exact exception class names differ per SDK; the semantics do not.

```python
try:
    cluster.transactions.run(txn_logic)

except TransactionCommitAmbiguous:
    # The commit was sent but the response was lost. The transaction MAY have
    # committed. Do NOT retry blindly — you may double-apply.
    # Inspect the database to determine the truth.
    check_and_reconcile()

except TransactionExpired:
    # Did not commit within the expiry window (default 15s) and was rolled back.
    # Safe to retry from the application side.
    raise RetryableError("Transaction timed out, please retry")

except TransactionFailed:
    # Failed for a reason the API will not retry — commonly a business-logic
    # exception raised inside the lambda. Deterministic; do not retry.
    raise
```

**`TransactionCommitAmbiguous` is the one that catches people out.** The commit was sent and the response was lost to a network issue or node restart. The transaction may or may not have committed. There is no safe automatic retry — you must look at the data. Design for it up front with an idempotency key.

Note the interaction with expiry: expiry can occur mid-commit, in which case the cleanup process completes or rolls back the work asynchronously. Your application sees the error before the cluster has finished resolving it, so a reconciliation read immediately afterwards may still be racing.

## The idempotency key pattern

Write a marker document inside the same transaction, keyed by a caller-supplied idempotency key. If the transaction committed, the marker exists; if not, it does not. This turns `TransactionCommitAmbiguous` into a lookup.

```python
def safe_transfer(cluster, from_id, to_id, amount, idempotency_key=None):
    if idempotency_key is None:
        idempotency_key = str(uuid.uuid4())

    scope    = cluster.bucket("bank").scope("_default")
    txn_log  = scope.collection("txn_log")
    accounts = scope.collection("accounts")

    def txn_logic(ctx):
        try:
            ctx.get(txn_log, idempotency_key)
            return                      # already applied — nothing to do
        except DocumentNotFoundException:
            pass

        from_doc = ctx.get(accounts, from_id)
        to_doc   = ctx.get(accounts, to_id)

        from_data = from_doc.content_as[dict]
        to_data   = to_doc.content_as[dict]

        if from_data["balance"] < amount:
            raise ValueError("Insufficient funds")

        from_data["balance"] -= amount
        to_data["balance"]   += amount

        ctx.replace(from_doc, from_data)
        ctx.replace(to_doc, to_data)
        ctx.insert(txn_log, idempotency_key, {
            "from_id": from_id, "to_id": to_id, "amount": amount,
            "committed_at": datetime.now(timezone.utc).isoformat(),
        })

    cluster.transactions.run(txn_logic)
    return idempotency_key
```

The key must come from the caller for this to survive a client crash — a key generated inside the function is lost along with the process. Give the marker documents a TTL long enough to cover your retry window.

## SQL++ transactions

For ad-hoc changes, transactional constructs are available directly in SQL++, from cbq, the Query Workbench, the CLI, the REST API, or an SDK.

```sql
BEGIN TRANSACTION;
  UPDATE customer SET c_balance = c_balance - 1000 WHERE c_first = "Beth";
  UPDATE customer SET c_balance = c_balance + 1000 WHERE c_first = "Andy";
COMMIT TRANSACTION;
```

Statements: `BEGIN TRANSACTION` (`START TRANSACTION`), `SET TRANSACTION`, `SAVEPOINT`, `ROLLBACK TRANSACTION`, `COMMIT TRANSACTION`.

How SQL++ transactions differ from SDK transactions:

| | SDK transactions | SQL++ transactions |
|---|---|---|
| Composition | A lambda that the API retries for you | A sequence of statements you drive yourself |
| Retry on conflict | Automatic | Yours to implement |
| Operations | KV ops and Query DML, mixed | **DML only** — `INSERT`, `UPSERT`, `DELETE`, `UPDATE`, `MERGE`, `SELECT`, `EXECUTE FUNCTION`, `PREPARE`, `EXECUTE` |
| Node affinity | Distributed across data nodes | **All statements go to the same Query node** |
| Savepoints | — | `SAVEPOINT`, with rollback to a savepoint |
| Statement failure | Aborts the attempt | **Statement-level atomicity** — the failed statement rolls back alone and the transaction continues |
| Memory profile | — | Maintains a **delta table** that grows with every mutation |

Tool-specific behaviour:

- **Query Workbench** — compose the statements in the editor, terminating each with a semicolon and pressing Shift+Enter between them, then Execute. `txid` and `tximplicit` are not needed. Other parameters go in the run-time preferences window.
- **cbq shell** — once a transaction is started, every statement in the session is part of it until you commit or roll back; no `txid` needed. Parameters are set with `\SET`.
- **Query REST API** — after starting the transaction you **must** set the `txid` parameter on each subsequent statement.

Relevant parameters and settings: `txid`, `tximplicit`, `txstmtnum`, `kvtimeout` (default 2.5 s), `durability_level`, `txtimeout` / `queryTxTimeout`, `atrcollection`, `numatrs` / `queryNumAtrs` (default 1024), `cleanupwindow` / `queryCleanupWindow`, `cleanupclientattempts`, `cleanuplostattempts`, and `scan-consistency`.

Source: [SQL++ Support for Couchbase Transactions](https://docs.couchbase.com/server/current/n1ql/n1ql-language-reference/transactions.html)

## Single query (implicit) transactions

A single statement can be run as its own transaction — `transactions.query(statement)` from an SDK, **Run as TX** in the Query Workbench, or the `tximplicit` request parameter (default `false`).

This is the recommended shape for **ETL-like loads and massive updates that still need ACID guarantees**, because single query transactions do not maintain a delta table and therefore avoid the memory growth that multi-statement query transactions incur.

## Savepoints

A savepoint is a user-defined intermediate state available for the duration of a transaction. In a long-running transaction you can roll back to a savepoint instead of discarding the whole transaction. Savepoints exist only within the transaction's context (for example `ctx.query("SAVEPOINT")` inside a lambda) and are removed on commit or rollback.

## Configuration

Configure transactions on the cluster environment rather than per call where the SDK offers both. The knobs that matter:

- **Transaction timeout** — the maximum lifetime of a transaction; **default 15 seconds**, after which it aborts (possibly mid-commit, leaving cleanup to finish). Raising it also raises how long documents can stay locked by a stalled transaction.
- **Durability level** — `majority` (default), `majorityAndPersistActive`, or `persistToMajority`. `NONE` is not supported.
- **Cleanup window** — how often active transaction records are checked for expired transactions.
- **Metadata collection** — a custom collection for ATR and client records. Transactions created from that configuration use it, and their cleanup looks only there.
- **`kvtimeout`** — per-KV-operation wait inside a transaction; default 2.5 s.

```python
# Shape only — check your SDK version's API for exact names.
txn_config = TransactionConfig(
    timeout=timedelta(seconds=30),          # default 15s
    cleanup_window=timedelta(seconds=60),
    durability_level=DurabilityLevel.MAJORITY,
)
```

Increase the timeout only when the transaction genuinely needs longer, and treat needing it as a signal to revisit the design.

Deployment prerequisites worth re-stating here because they surface as configuration bugs: **NTP must be running on all cluster nodes**, and on a single-node development cluster you must set bucket replicas to 0 and rebalance, or every durable write fails with `DurabilityImpossibleException`.
