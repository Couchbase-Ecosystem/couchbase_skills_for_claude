# Transaction mechanics

## Contents

- [Attempts, staging, and the commit point](#attempts-staging-and-the-commit-point)
- [Active Transaction Records (ATRs)](#active-transaction-records-atrs)
- [Custom metadata collections](#custom-metadata-collections)
- [Isolation: Read Committed, and MAV for reads](#isolation-read-committed-and-mav-for-reads)
- [Durability](#durability)
- [Retry and expiry](#retry-and-expiry)
- [Lost update prevention and write-write conflicts](#lost-update-prevention-and-write-write-conflicts)
- [Asynchronous cleanup](#asynchronous-cleanup)
- [Transactions and the other services](#transactions-and-the-other-services)
- [Query mode and permissions](#query-mode-and-permissions)
- [Transactions and XDCR](#transactions-and-xdcr)
- [Performance characteristics](#performance-characteristics)
- [Monitoring](#monitoring)

## Attempts, staging, and the commit point

Each execution of the transaction lambda is an **attempt** within the overall transaction. The mechanics, in order:

1. **ATR entry created.** The attempt adds an entry to an Active Transaction Record — a metadata document in the cluster. The entry records, crucially, whether the attempt has committed. It is the single point of truth for the transaction.
2. **Mutations staged.** Mutating a document inside a transaction does **not** change the document body. The post-transaction version is staged alongside the document, technically in its **extended attributes (XATTRs)**. All changes are therefore invisible to every part of the cluster until the commit point.
3. **Commit.** Once the lambda has run to conclusion, the ATR entry is updated to committed. **Updating that ATR entry is the atomic commit switch** for the whole transaction — from that moment, transactional readers use the post-transaction version from the XATTRs.
4. **Unstaging.** The individual documents are then committed: the staged version replaces the body and the staging metadata is removed. This gives an eventually consistent commit for non-transactional readers, including plain KV reads.
5. **Completion.** The attempt is marked complete and removed from the ATR.

If the client crashes **after** the ATR entry is marked committed but before unstaging finishes, another actor or the cleanup process finishes the commit. If it crashes **before** the ATR commit, the transaction is rolled back. Documents are never left in an inconsistent state.

Source: [Transactions](https://docs.couchbase.com/server/current/learn/data/transactions.html)

## Active Transaction Records (ATRs)

ATRs are metadata documents created and maintained automatically. They are identifiable by the prefix `_txn:atr-`. Each ATR holds entries for multiple attempts, and each entry carries the document keys plus the bucket, scope, and collection for the documents involved.

- **Default location:** the default collection of the bucket of the **first mutated document** in the transaction. Not "one per collection".
- **Count:** the total number of active transaction records is governed by the `numatrs` node-level setting (`queryNumAtrs` at cluster level), whose **default is 1024**, with a minimum above 0. This is a Query Service setting. ([Query settings](https://docs.couchbase.com/server/current/settings/query-settings.html))
- For SQL++ transactions, the `atrcollection` request-level parameter or node-level setting chooses where ATRs and client records are stored. The collection must already exist.

**Do not delete ATR documents manually.** They are documented as viewable but not to be modified externally; deleting them can lose transactions. Do not poll `_txn:` keys in production loops either — they are transient.

Persistent `_txn:atr-*` documents that are not clearing usually mean orphaned transactions from crashed clients. That is what the cleanup process is for — see below.

## Custom metadata collections

By default the metadata (ATR) documents land in the default collection of the first mutated document's bucket. You can nominate a **custom metadata collection** instead, via the SDK's transactions configuration (`metadataCollection`) or the `atrcollection` parameter in SQL++.

Two consequences worth stating:

- Every transaction created from that configured object uses that collection, and its asynchronous cleanup looks for expired transactions **only** in that collection. Mixing configurations across an application fleet can leave some transactions uncleaned.
- A custom metadata collection with its own RBAC lets you control who can see transaction metadata, and lets you remove the default collection if your deployment needs that.

## Isolation: Read Committed, and MAV for reads

Couchbase states the isolation level as **Read Committed**: changes made in a transaction are not visible until it commits.

But the guarantee for transactional reads is **stricter than Read Committed — it is Monotonic Atomic View (MAV)**. MAV ensures that all effects of a previously committed transaction are observed: after commit, a transaction is never partially observed.

Alongside that:

- You see your own uncommitted writes within the same transaction.
- Other transactions cannot see your uncommitted writes.
- **Lost updates are always prevented** by checking against the CAS value, which behaves like an optimistic lock.
- There is no Serializable isolation. For serializable semantics, use CAS-based locking or design out the conflict.

For SQL++, `BEGIN TRANSACTION` accepts `ISOLATION LEVEL READ COMMITTED`, and that is **the only available transaction setting** — it is enabled by default and the keywords are optional.

Note also **statement-level atomicity** for SQL++ statements inside a transaction: if a query statement fails mid-execution (for example a unique key violation), that statement is rolled back completely and the rest of the transaction continues, as if the statement had never been part of it. If it succeeds, it commits or rolls back with the overall transaction.

## Durability

Transactions use durable writes, with three tunable levels:

| Level | Meaning |
|---|---|
| `majority` (**default**) | Replicated to a majority of replicas before acknowledgement |
| `majorityAndPersistActive` | Replicated to a majority and persisted to disk on the active before acknowledgement |
| `persistToMajority` | Persisted to disk on a majority of replicas before acknowledgement — strongest protection, least performant |

`NONE` is **not supported** and provides no ACID transactional guarantees.

Two deployment traps:

- On a single-node cluster, a new bucket defaults to 1 replica, so durable writes fail with `DurabilityImpossibleException`. Set replicas to 0 and rebalance.
- Couchbase Server 8.0 adds a cluster-level option to let durable writes succeed even when they cannot meet their majority requirement after a failover. The documentation is explicit that this **degrades the guarantee durable writes offer**, makes such writes no safer than asynchronous writes, and means **transactions do not provide the same guarantees while it is on**. Use it only for a specific operation such as a graceful failover, and turn it off immediately afterwards. ([What's New in 8.0](https://docs.couchbase.com/server/current/introduction/whats-new.html))

## Retry and expiry

Transactions retry automatically on transient failures — write conflicts, temporary node unavailability. The SDK rolls back what it has done and runs the lambda again; the application does not implement the retry loop.

- **Transaction expiry timer: default 15 seconds.** It starts ticking when the transaction starts. Within that window, concurrency or node issues are handled by a combination of waits and retries. If the transaction has not committed by then, it is rolled back and an expiry error is raised. ([TransactionsConfig](https://docs.couchbase.com/sdk-api/couchbase-java-client/com/couchbase/client/java/transactions/config/TransactionsConfig.html))
- Expiry can abort mid-commit, in which case the cleanup process finishes or rolls back the work.
- **`kvtimeout` default is 2.5 seconds** — the maximum wait for a single KV operation inside a transaction.
- Because documents mutated in transaction A are effectively locked against other transactions until A completes, a transaction that stalls can lock its documents for the full expiry window. That is the real cost of raising the expiry.

**Your lambda may run more than once, so it must be safe to re-run.** Generate identifiers and timestamps *inside* the lambda so each attempt is self-consistent:

```python
# WRONG — the id is fixed outside the lambda but the lambda may retry
new_id = str(uuid.uuid4())
def txn_logic(ctx):
    ctx.insert(collection, new_id, {...})

# CORRECT — generated per attempt
def txn_logic(ctx):
    new_id = str(uuid.uuid4())
    ctx.insert(collection, new_id, {...})
```

If a transaction genuinely needs seconds to complete, question the design before raising the expiry.

## Lost update prevention and write-write conflicts

Staged document changes act as a lock against other transactions trying to modify the same document, which is what prevents write-write conflicts. CAS is checked internally, so lost updates are always prevented. There is no last-write-wins inside transactions: a conflict is detected and the losing attempt retries.

Non-transactional writes are the hole in this. A plain KV write to a document involved in an in-flight transaction can interfere with transactional integrity, or be overwritten. Applications should never perform non-transactional writes concurrently with transactional ones on the same document.

## Asynchronous cleanup

Safety mechanisms stop leftover staged changes from a failed transaction blocking live transactions indefinitely. An asynchronous cleanup process starts with the creation of the Transactions object and scans for expired transactions created by **any** application, on all buckets (or only the configured custom metadata collection, if one is set).

**If no application is running, cleanup is not running.** A fleet that scales to zero leaves orphaned staged changes until something comes back up. The `cleanupWindow` setting governs how frequently active transaction records are checked; `cleanupclientattempts` / `cleanuplostattempts` (and their cluster-level `queryCleanup*` equivalents) control the SQL++ side.

## Transactions and the other services

- **All Couchbase services only ever see committed data.** Uncommitted (dirty) transactional modifications are never visible to any service.
- Index, Search, and Analytics indexes are **not** synchronously updated on commit — they update with eventual consistency. A query run immediately after a commit may not see the transaction's effects.
- Inside a transaction, query scan consistency defaults to **`request_plus`**, so queries see everything committed before the transaction started, plus the transaction's own work. You can drop to `not_bounded` when the query uses `USE KEYS`, when the data is known not to be recently updated, or for `UPSERT`/`INSERT` statements that do not care.

## Query mode and permissions

When a transaction executes a query statement, it enters **query mode**: the query runs with the user's *query* permissions, and **so do any key-value operations the transaction performs afterwards**. If a user's query permissions differ from their data permissions, this produces surprising results. Grant them consistently, or keep KV operations before the first query statement.

## Transactions and XDCR

XDCR supports eventual consistency of transactional changes, with important caveats:

- No uncommitted changes are ever sent to a target cluster.
- Committed changes arrive at the target **one by one**, so a connection lost mid-stream can leave the target holding a **partial transaction**.
- Document counts differ between source and target because transaction metadata documents are never replicated. Do not use count parity as a health check.
- **Active-active bidirectional replication with transactions is not advised.** If it is used anyway, transactions must not run against the same documents on both clusters: each cluster's applications own a mutually exclusive, key-identified set of documents, and a failed transaction is retried **on the same cluster**.
- When transactions are used with XDCR, Couchbase strongly recommends **timestamp-based conflict resolution** and following the documented safe-failover procedure.

## Performance characteristics

State this qualitatively. A transactional update requires more writes than a non-transactional one — staging into XATTRs, ATR creation and update, unstaging, plus any retries — so it may be less performant. How much less depends on the number of documents, how they are distributed across nodes, the durability level, storage latency, and the conflict rate. Profile your own workload rather than assuming a ratio.

Two specific levers:

- **Durability level** is usually the largest single factor: `persistToMajority` is explicitly documented as the least performant.
- **Query statements inside a transaction maintain a delta table that grows with every mutation**, increasing memory use. Limit the number of mutations, and manage the ceiling with the Query Service `memory-quota` setting. For ETL-like loads or massive updates that still need ACID guarantees, use **single query transactions** (implicit transactions, via `tximplicit` or "Run as TX"), which do not maintain a delta table.

## Monitoring

Use the `system:transactions` catalog to see active transactions on the cluster. This is the right place to look when you suspect stuck transactions, rather than querying `_txn:` keys.
