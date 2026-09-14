---
name: couchbase-transactions
description: "Design and implement Couchbase distributed ACID transactions across multiple documents. Use whenever the user asks about transactions, multi-document atomicity, ACID guarantees, the transactions lambda, commit and rollback, transaction retry, Active Transaction Records (ATRs), transaction expiry, staged mutations, transaction cleanup, TransactionCommitAmbiguous, SQL++ BEGIN/COMMIT/ROLLBACK and tximplicit, savepoints, or 'how do I atomically update multiple documents.' Distinct from couchbase-app-integration, which covers single-document KV and subdocument operations with only a brief transactions overview — this skill is for designing around transactions, understanding the two-phase commit mechanics, and debugging failures. Use proactively when a use case requires consistency across multiple documents."
license: Apache-2.0
---

# Couchbase Distributed Transactions

A skill for *designing and implementing* multi-document ACID transactions in Couchbase. Goes deeper than the overview in `couchbase-app-integration`.

## When this skill applies

- "How do I atomically update multiple documents?"
- "How do transactions work under the hood?"
- "My transaction is retrying — why?"
- "What happens if the client crashes mid-transaction?"
- "What are ATRs and why does my bucket have them?"
- "SQL++ BEGIN/COMMIT vs SDK transactions — what's the difference?"
- "What is *not* allowed inside a transaction?"
- "How do I model data to avoid needing transactions?"

## Pick the right reference

| Question | Read |
|---|---|
| "When should I use a transaction vs a single-document op vs subdoc?" | `references/when-to-use.md` |
| "How do they work? ATRs, staging, two-phase commit, isolation, retry, expiry, cleanup" | `references/mechanics.md` |
| "Code patterns, error handling, SQL++ transactions, configuration" | `references/patterns.md` |

## What is supported

- **Distributed, multi-node, multi-bucket.** A transaction spans documents on multiple nodes, and across multiple collections, scopes, and buckets. Only the nodes holding data to be updated are involved.
- **SDKs with a documented distributed-transactions API:** C++, .NET, Go, Java, Kotlin, Node.js, PHP, Python, and Scala.
- **Operations:** key-value `insert`, `replace`, and `remove` across any number of documents, seamlessly mixed with Query DML statements (`SELECT`, `INSERT`, `UPDATE`, `DELETE`, `UPSERT`, `MERGE`) in the same transaction.
- **SQL++ transactions** for ad-hoc work, from cbq, the Query Workbench, the CLI, the REST API, or an SDK.

([Transactions](https://docs.couchbase.com/server/current/learn/data/transactions.html))

The transactions documentation does not carry an Enterprise Edition banner, unlike the XDCR and Eventing pages. Do not assert either way in a customer conversation without checking the edition matrix for the specific release they run — and note that some things transactions depend on, such as the durability behaviour and the services around them, have their own edition characteristics.

## Core principle: design around transactions where you can

Transactions do more work than the equivalent single-document write: each mutation is staged in the document's extended attributes, an Active Transaction Record is written and updated, and attempts may be retried. Couchbase's own documentation puts it as "the number of writes required by a transactional update is greater than the number required for a non-transactional update. Thus transactional updates may be less performant than non-transactional updates."

That is the honest statement. **Do not quote a multiplier.** The real cost depends on document count, node distribution, durability level, storage latency, and conflict rate; measure it on your own workload if the number matters.

Data within a single document is always updated atomically without a transaction. Whenever practical, model so that values which must change together live in one document. See `references/when-to-use.md`.

## Non-negotiable constraints

- **Documents must be under 10 MB** to be used in transactions.
- **Do not perform non-transactional writes to a document while a transaction involving it is in flight.** The interaction can compromise the integrity of the transactional update, or silently overwrite the non-transactional one.
- **NTP is required** — transactions need synchronised clocks across all cluster nodes.
- **On a single-node cluster** (typically development), a new bucket defaults to 1 replica, so the durable writes transactions rely on fail with `DurabilityImpossibleException`. Set replicas to 0 and rebalance.
- **Durability `NONE` is not supported** and provides no ACID guarantees. The default is `majority`.
- **Asynchronous cleanup only runs while an application is running.** If nothing using the transactions API is up, expired transactions are not cleaned up.

## Operating

Transactions are application code. Drive them from an SDK, or from SQL++ for ad-hoc work.

The official Couchbase MCP server (`couchbase/mcp-server-couchbase`, https://mcp-server.couchbase.com/) is a data-plane server that is **read-only by default** (`CB_MCP_READ_ONLY_MODE`) and exposes no transaction API. Use it to inspect documents before and after a transaction, and use `system:transactions` to monitor active transactions; write the transaction itself in application code or SQL++.

## Related skills

- `couchbase-app-integration` — SDK setup and the single-document operations transactions are built on
- `couchbase-data-modeling` — modelling decisions that remove the need for transactions
- `couchbase-xdcr` — Couchbase advises against active-active bidirectional XDCR with transactions; see `references/mechanics.md`
- `couchbase-coding-standards` — how transaction lambdas, retries and error handling should look in production code
