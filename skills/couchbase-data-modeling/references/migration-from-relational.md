# Migrating from another database

When the user is coming from PostgreSQL, MySQL, Oracle, SQL Server, MongoDB, or DynamoDB, half the modeling battle is unlearning instincts. This reference covers the common pitfalls of translating an existing schema to Couchbase and the right way to think about the same problems.

## Contents

- [The fundamental shift](#the-fundamental-shift)
- [Translation table](#translation-table)
- [Patterns that translate well](#patterns-that-translate-well)
- [Patterns that DON'T translate well](#patterns-that-dont-translate-well)
- [Patterns that are easier in Couchbase](#patterns-that-are-easier-in-couchbase)
- [Two migration approaches](#two-migration-approaches)
- [Specific source-DB notes](#specific-source-db-notes)
- [Coming from MongoDB](#coming-from-mongodb)
- [Coming from DynamoDB](#coming-from-dynamodb)
- [Tooling: cbmigrate](#tooling-cbmigrate)
- [Don't migrate everything at once](#dont-migrate-everything-at-once)
- [Quick decision tree](#quick-decision-tree)

## The fundamental shift

Relational: third-normal form by default, denormalize only when forced to by performance.

Document: model the access patterns by default, normalize only when forced to by write patterns.

Concretely: in SQL you'd start with separate `users`, `orders`, `order_items`, `addresses` tables and JOIN them at query time. In Couchbase, you'd start with what the application actually reads — perhaps a user document that embeds addresses (1:few, read with the user) and references orders (1:many, separate documents).

The shift isn't "denormalize everything" — it's "let the access pattern, not the entity relationships, drive the structure."

## Translation table

A direct mapping of relational concepts to Couchbase concepts:

| Relational | Couchbase | Notes |
|---|---|---|
| Database | Bucket | Roughly. Bucket is more "container with its own memory budget" |
| Schema | Scope | Both are namespacing within the container |
| Table | Collection | Type-grouping of documents |
| Row | Document | One JSON document per "row" |
| Primary key | Document key (META().id) | Couchbase's key IS the PK; no separate column |
| Column | JSON field | Documents have free shape; no enforced columns |
| Foreign key | Field containing another doc's key | No enforcement — application's job |
| JOIN | SQL++ ANSI JOIN, or denormalize, or separate fetches | All three are valid; pick by access pattern |
| Index | GSI (global secondary index) | Similar concept, different mechanics |
| Stored procedure | Eventing function (EE), or a SQL++ user-defined function | Eventing is event-driven; UDFs run at query time |
| Trigger | Eventing function (EE) | Eventing functions are triggered by document mutations |
| View | SQL++ query, or a maintained summary document | Or the Analytics service (EE) for analytical views |
| Transaction | Distributed ACID transaction via the SDKs, or `BEGIN TRANSACTION` in SQL++ | Slower than a plain KV write; use when atomicity across documents genuinely matters |

## Patterns that translate well

These relational patterns work essentially the same in Couchbase:

- **Lookup by ID**: `SELECT * FROM users WHERE id = 42` → a KV get on key `user::42`. Couchbase is much faster here because KV needs no index and no query planning
- **Filtering by indexed column**: `SELECT * FROM users WHERE tier = 'gold'` → the same SQL++ with a GSI on `tier`
- **Aggregation**: `SELECT COUNT(*), AVG(value) FROM ... GROUP BY ...` → the same SQL++. Move it to the Analytics service (EE) if it's a heavy ad-hoc query you don't want competing with the operational workload
- **Many-to-many through a join table**: keep the join table pattern (bridge documents). Doesn't translate to embedding when both sides are unbounded

## Patterns that DON'T translate well

### "I'll just use SQL++ JOINs for everything"

You can. `SELECT u.*, o.* FROM users u JOIN orders o ON u.id = o.user_id` is valid SQL++. But:
- JOINs need an index on the join key, at minimum on the inner/probe side
- Hash joins are **Enterprise Edition only** — on Community Edition the planner only ever considers nested-loop joins
- Distributed JOINs across nodes have network cost
- It's often faster to fetch the parent doc (KV), then issue a follow-up KV multi-get for the children, than to JOIN

The right mental shift: ask "do I need ALL fields of both, or only a subset?" If subset, project the subset. If all, consider denormalization or two KV fetches.

### "Normalize everything"

The relational instinct of "Customer has Address, so Address is a separate table" produces models like:

```json
// users collection
{ "id": "user::42", "name": "Alice", "address_id": "addr::789" }

// addresses collection  
{ "id": "addr::789", "street": "...", "city": "...", ... }
```

This means every user lookup is two KV fetches (or one JOIN). For something as 1:1-with-user as an address, embed it:

```json
{
  "id": "user::42",
  "name": "Alice",
  "address": { "street": "...", "city": "...", ... }
}
```

One fetch, simpler code, no inconsistency window.

### "I need a sequence for IDs"

SQL has `SERIAL` / `AUTO_INCREMENT`. Couchbase has an atomic counter operation (see `keys.md`), but reaching for it by default is usually a mistake.

Reasons to prefer ULIDs over sequential IDs in Couchbase:
- No write hot spot (sequential IDs hash to similar vBuckets)
- Time-orderable (ULIDs sort by creation time)
- Distributed-friendly (multiple clients can generate IDs without coordination)
- No counter document to maintain

The exception: when users need to remember/type the ID (invoice numbers, order references). Then use a counter, accept the hot-spot cost, and consider sharding the counter.

### "I'll use a single table for polymorphic data"

In SQL, the pattern of `polymorphic_table(id, type, common_fields..., type_specific_fields...)` with sparse columns is a known smell but sometimes used.

In Couchbase the equivalent looks fine — documents in the same collection can have different shapes. But it falls apart fast:
- Indexes have to handle all the shapes
- Schema-by-accident emerges
- Queries become hard to optimize

Better: separate collections per type, even if they share a few common fields. The few common fields can be denormalized into both.

## Patterns that are easier in Couchbase

### Nested data

Relational: `user has address has city has country has ...` requires many tables and JOINs.

Couchbase: just nest it.

```json
{
  "id": "user::42",
  "addresses": [
    {
      "type": "home",
      "street": "...",
      "city": { "name": "Seattle", "country": { "code": "US", "name": "USA" } }
    }
  ]
}
```

A single fetch gets you everything.

### Optional fields and varying schemas

Relational: every column exists for every row; optional fields are NULL.

Couchbase: fields just don't exist if they don't apply. A `temporary` user might have an `expires_at` field that permanent users don't have. Code uses `IS MISSING` to check.

This is genuinely easier than the relational equivalent.

### Adding a field

Relational: `ALTER TABLE` and possibly a long migration.

Couchbase: just start writing the new field. Old documents without it have it missing; queries handle that via `IS MISSING` or `IFMISSING()`. Use a `_v` field if you want explicit migration tracking.

## Two migration approaches

If you're actually migrating an existing relational DB to Couchbase:

### Approach 1 — Direct translation (anti-pattern)

Take each relational table and turn it into a Couchbase collection. Same schema, same keys, same foreign-key fields.

**Problem:** you've spent the migration cost and ended up with a relational design in a document database. You get neither the consistency benefits of relational nor the access-pattern benefits of document. The application code still issues JOIN-equivalent queries; performance is no better.

This is the most common migration outcome and almost always regretted.

### Approach 2 — Re-model for access patterns

For each user-facing read in the application:
1. List every relational table involved
2. Ask "could these be one document?"
3. If yes (1:1 or bounded 1:few), embed
4. If no (unbounded 1:many or many:many), separate documents with references

Result: fewer collections than tables, but each collection's documents are richer.

**Cost:** the migration is bigger because the schema fundamentally changed. Application code also needs adjusting (KV gets instead of JOINs).

**Payoff:** queries that took JOINs in SQL become single KV fetches.

### Hybrid: cold-side translation, hot-side re-model

For low-traffic reads (admin reports, batch jobs), direct translation is fine — the slight inefficiency doesn't matter and the migration is faster.

For high-traffic reads (the actual app pages), re-model for access patterns.

This pragmatic split is often the right answer.

## Specific source-DB notes

### From PostgreSQL

- JSONB columns translate trivially — they're already JSON
- Sequences → ULIDs or per-doc keys (avoid the counter pattern unless needed)
- PL/pgSQL stored procedures → Eventing functions (JavaScript, EE) or SQL++ user-defined functions
- Materialized views → the Analytics service (EE) or maintained summary documents
- LISTEN/NOTIFY → Eventing functions (EE) react to document mutations

### From MySQL

- AUTO_INCREMENT → ULID (much better) or counter
- ENUM columns → string field with application-level validation
- Stored procedures → Eventing functions (EE)
- Replication → XDCR (**EE only**; a different model — bidirectional is possible and conflict resolution is configurable. Couchbase 8.0 adds XDCR conflict logging)

### From Oracle

- Sequences → ULID or counter
- Materialized views → the Analytics service (EE)
- PL/SQL → Eventing functions (JavaScript, EE)
- DBA Privileges → Couchbase RBAC roles; see the `couchbase-mcp` skill's security-best-practices reference

### From SQL Server

- Identity columns → ULID
- T-SQL stored procedures → Eventing functions (EE)
- Filtered indexes → partial indexes, which take a `WHERE` clause in `CREATE INDEX`. `INCLUDE MISSING` (7.1+) is a related but different tool: it indexes documents where the *leading key* is absent

## Coming from MongoDB

The document model transfers almost directly — BSON documents become JSON documents, and the embed-vs-reference reasoning in `document-shape.md` is the same reasoning. What needs rethinking:

| MongoDB | Couchbase | Note |
|---|---|---|
| Database | Bucket | Bucket also owns the memory quota and replica count |
| Collection | Scope + collection | Couchbase has one more level; use scopes for tenant or environment separation |
| `_id` | Document key | Same role. Couchbase keys are strings up to 250 bytes and are not stored in the body unless you put them there |
| Aggregation pipeline | SQL++ query, or the Analytics service (EE) for heavy work | SQL++ is a query language, not a pipeline — expect to rewrite, not translate |
| Index on a nested field | GSI on the same path | Same idea; see `access-patterns.md` for keeping the path stable and the type consistent |
| Change streams | Eventing functions (EE), or a DCP-based consumer | |

The most common mistake: keeping a `_id` field in the document body that duplicates the key. In Couchbase the key is metadata, reachable as `META().id`; store it in the body only if you specifically need to index or project it.

## Coming from DynamoDB

The mental shift is larger here, because DynamoDB's single-table design exists to work around a query model Couchbase doesn't have.

| DynamoDB | Couchbase | Note |
|---|---|---|
| Table | Collection | |
| Partition key + sort key | Document key, usually composite | Couchbase has no separate sort key; encode the ordering component in the key, or index the field |
| Single-table design with overloaded keys | Separate collections per type | The main thing to *undo*. Couchbase can query across documents with a GSI, so you don't need to overload one table |
| GSI / LSI | GSI | Couchbase secondary indexes are not limited the way LSIs are |
| Query / Scan | SQL++ with a GSI | A DynamoDB `Scan` maps to an unindexed scan, which you should be designing away |
| TTL attribute | Document expiry, or collection `maxTTL` | See `time-series-and-ttl.md` for the precedence rules |
| Streams | Eventing functions (EE), or a DCP-based consumer | |

The most common mistake: porting the single-table design intact. Overloaded generic attribute names (`PK`, `SK`, `GSI1PK`) are a workaround for a limitation Couchbase doesn't share, and carrying them over gives you an unreadable model with none of the benefits. Split by type into collections and index the fields you actually query.

## Tooling: cbmigrate

Couchbase ships a `cbmigrate` CLI that moves data in from **MongoDB**, **DynamoDB**, and **Hugging Face**. Useful flags for the modeling decisions above:

- `--cb-generate-key` builds document keys from static text, field values (`%fieldname%`) and generators such as `#UUID#` — this is where your key design from `keys.md` gets applied
- `--cb-scope` and `--cb-collection` target the destination, so you can split one source table across several collections by running it more than once
- `--copy-indexes` brings source indexes across; review what it produces rather than accepting it, since the right Couchbase index usually isn't a one-to-one translation

Treat `cbmigrate` as the mechanism, not the design. It will happily reproduce a relational or single-table model verbatim — which is Approach 1 below.

## Don't migrate everything at once

For any non-trivial migration:

1. Pick one bounded slice of the application (one feature, one module)
2. Re-model just that slice for Couchbase
3. Run dual-write: write to both old DB and Couchbase for the slice
4. Read from Couchbase, verify it matches; if not, fix and continue dual-write
5. Once stable, cut reads over to Couchbase entirely
6. Eventually remove the relational tables for that slice
7. Repeat for the next slice

Big-bang migrations of relational to document have a high failure rate. Slicing keeps the blast radius small at each step.

## Quick decision tree

- **Direct ID lookup?** → KV get, faster than relational
- **1:1 or bounded 1:few?** → embed in the parent document
- **1:many unbounded or many:many?** → separate documents, links via foreign-key-style field
- **Polymorphic table?** → separate collections per type
- **Need transactions across multiple docs?** → a distributed ACID transaction via the SDK or `BEGIN TRANSACTION` (slower than KV; use sparingly)
- **Migrating?** → re-model for access patterns on hot paths; direct translation on cold paths
- **Need ALTER TABLE?** → you don't; just start writing the new field and use a version marker
