# When to use transactions

## Contents

- [The decision ladder](#the-decision-ladder)
- [Good transaction use cases](#good-transaction-use-cases)
- [Poor transaction use cases](#poor-transaction-use-cases)
- [What you cannot do inside a transaction](#what-you-cannot-do-inside-a-transaction)
- [Modelling to avoid transactions](#modelling-to-avoid-transactions)

## The decision ladder

Before reaching for a transaction, check whether a cheaper primitive covers the need.

| Tool | Scope | Guarantee |
|---|---|---|
| Single KV write (`upsert`, `insert`, `replace`) | 1 document | The document is written atomically |
| Sub-document operation (`mutate_in`) | 1 document, multiple paths | Atomic multi-field update within the document |
| CAS-based optimistic lock | 1 document | Prevents lost updates; the caller retries on conflict |
| **Distributed transaction** | Multiple documents | All-or-nothing atomicity across them |

Couchbase's own guidance: **data within a single document is always updated atomically without a transaction**, so whenever practical, design the data model such that a single document holds the values that must change together.

Cost is not a fixed ratio. A transactional update needs more writes than a non-transactional one — staging, ATR bookkeeping, unstaging, and any retries — so it may be less performant. Measure on your own workload rather than quoting a multiplier.

**If the operation touches only one document:** use a KV write or `mutate_in`.

**If it touches two documents but only one needs a consistent view:** consider embedding the relevant fields of the second into the first. Often cheaper than a transaction.

**If you need genuine all-or-nothing across two or more documents:** use a transaction.

## Good transaction use cases

**Financial transfers.** Debit one account, credit another — both or neither.

**Inventory and order.** Reserve stock and create the order atomically.

**Multi-document state machine.** Advance a workflow that touches a status document and a history document together.

**Referential integrity at creation.** Create a parent document and its first child atomically.

In all four, the shared property is that a partially applied change would be visibly wrong to a reader and not self-correcting.

## Poor transaction use cases

**Incrementing a counter.** A sub-document counter operation on a single document is already atomic. No transaction needed. (Note this is atomic within one cluster only — it is not coordinated across XDCR.)

**Updating every document matching a query.** Query DML *is* allowed inside a transaction, but the delta table grows with every mutation and memory use rises with it. For ETL-like loads and massive updates that need ACID guarantees, use **single query transactions** (implicit transactions) instead, which maintain no delta table.

**Logging an event alongside a record update.** Append-only log writes do not need to be atomic with the record. Write them independently.

**Naturally idempotent operations.** If re-running the operation produces the same result, a CAS-checked write handles retries without transaction overhead.

**Anything touching documents over 10 MB.** Documents used in transactions must be under 10 MB.

**Anything where a non-transactional writer also touches the same documents.** Non-transactional writes must not be made to a document involved in an in-flight transaction — the interaction can compromise the transactional update, or silently overwrite the non-transactional one. If you cannot guarantee exclusivity, a transaction is not buying you what you think it is.

## What you cannot do inside a transaction

**In SQL++ transactions, only DML statements are permitted:** `INSERT`, `UPSERT`, `DELETE`, `UPDATE`, `MERGE`, `SELECT`, `EXECUTE FUNCTION`, `PREPARE`, and `EXECUTE`. No DDL — no `CREATE INDEX`, no `CREATE SCOPE`, no bucket or user management. Two further restrictions:

- `EXECUTE FUNCTION` is only permitted if the user-defined function contains no subqueries other than `SELECT` subqueries.
- `PREPARE` and `EXECUTE` are only permitted for the DML statements listed above.
- All statements in a SQL++ transaction go to the **same Query node**.

**Isolation levels other than Read Committed are not available.** `BEGIN TRANSACTION` accepts `ISOLATION LEVEL READ COMMITTED` and nothing else; it is the default and the keywords are optional. There is no Serializable option.

**Durability `NONE` is not supported** — it provides no ACID guarantees.

**Cross-cluster atomicity does not exist.** Transactions are ACID *within the same datacenter*. XDCR delivers committed changes one by one, so a target can hold a partial transaction if the connection drops mid-stream. Couchbase advises against combining transactions with active-active bidirectional XDCR.

**Uncommitted data is invisible to every service**, so you cannot rely on a query, Search, or Analytics seeing in-transaction state. And index updates after commit are eventually consistent, not synchronous.

## Modelling to avoid transactions

Document design is the most effective lever.

**Embed instead of reference.** If order items are always created and deleted with their order, embed them. Nothing to keep consistent across documents.

**Event sourcing.** Append an event (`{type: "credit", amount: 100, at: ...}`) rather than updating a balance in place. The balance is derived from the log. The append needs no transaction; consistency is eventual.

**Saga pattern.** Break a multi-step workflow into independent idempotent steps, each writing its own status, driven by a coordinator (an application or an Eventing function), with compensating actions on failure. More moving parts than a transaction, but it scales better and tolerates partial failure explicitly.

**Single document with sub-documents.** Combine things that always change together — an order and its shipping address — into one document and update them with `mutate_in`.

One caution on each: these patterns trade atomicity for eventual consistency and for complexity elsewhere. Choose them because the read pattern genuinely tolerates it, not to avoid learning the transactions API.
