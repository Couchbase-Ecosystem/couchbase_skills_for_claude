# Migration strategies — choosing the right approach

Four approaches, each suited to different constraints. Pick by working through the decision flow, not by what sounds easiest.

## Contents

- [Big-bang migration](#big-bang-migration)
- [Phased / strangler-fig migration](#phased--strangler-fig-migration)
- [Dual-write migration](#dual-write-migration)
- [CDC-based migration](#cdc-based-migration)
- [The decision flow](#the-decision-flow)
- [Combining strategies](#combining-strategies)
- [Anti-patterns](#anti-patterns)
- [Estimating effort](#estimating-effort)
- [Quick decision tree](#quick-decision-tree)

## Big-bang migration

Stop writes on source. Export everything. Load into Couchbase. Validate. Switch traffic.

**When to use:**
- Total data size is modest (< 100 GB; smaller is better)
- You can schedule downtime (maintenance window of hours)
- Source system has clear "stop accepting writes" mode
- Rollback plan is "switch back to source" — and that's acceptable

**Pros:**
- Simplest approach. No special tooling needed beyond bulk import
- Lowest engineering cost
- Easy to reason about — source is frozen, target is built once, done

**Cons:**
- Downtime is real (typically 2-24 hours depending on data size and validation)
- No "dual-running" period to catch transformation bugs in production
- Rollback after-the-fact is hard (data written to Couchbase post-migration is lost on rollback)

**Workflow:**

1. Stop writes on source (read-only mode or full downtime)
2. Wait for in-flight writes to drain (especially for distributed systems)
3. Export data from source
4. Transform (if shape change needed) — separate pass or pipeline through transformation
5. Bulk load into Couchbase — `cbmigrate` for MongoDB/DynamoDB/Hugging Face sources, `cbimport` for files (set `--threads`; the default is 1), or custom SDK code
6. Validate (count, samples, checksums)
7. Switch application traffic to Couchbase
8. Decommission source (optional, can defer)

**Reality check:** in practice "big-bang" often means "weekend migration." Plan for 48-72 hours total: a Friday evening start, validation through the weekend, Monday morning ready for users. Going faster pressures the validation step, which is where bugs are caught.

## Phased / strangler-fig migration

Migrate one slice of the application at a time. Each slice is its own mini-migration.

**When to use:**
- Application has natural boundaries (modules, microservices, domains)
- Total data is large enough that one big-bang is risky
- You can tolerate some slices on old system and some on new for a while
- Each slice is independent enough that you don't need transactional consistency across slices

**Pros:**
- Limits blast radius — one slice's failure doesn't affect others
- Builds team confidence — first slice teaches you what'll go wrong on later ones
- Easier rollback per slice (smaller scope)
- Production traffic exercises each migration as it happens

**Cons:**
- Longer total project timeline
- During migration period, the app is hybrid (some Couchbase, some source) — operational complexity
- Cross-slice queries may not work cleanly during transition

**Workflow:**

1. Identify slices (typically: per-microservice, per-domain, per-bounded-context)
2. Order them by risk (start with low-risk; build confidence)
3. For each slice:
   a. Migrate that slice (could itself be big-bang or dual-write)
   b. Validate
   c. Cutover for THAT slice's reads/writes to Couchbase
   d. Run for a soak period
   e. Decommission source for that slice
4. After all slices done: decommission source

**Strangler-fig** is the same pattern with a specific framing: the new system grows around the old until the old is "strangled" — gradually wrapped and replaced. Common in microservice migrations.

## Dual-write migration

App writes to BOTH source and target during transition. Reads can come from either; eventually reads cut over to target, then writes cut over.

**When to use:**
- Zero downtime requirement
- You control the application code (can modify writes)
- Sources can't be put in read-only mode for the time you'd need

**Pros:**
- Zero downtime
- Continuous validation — every write tests the transformation
- Rollback is just "stop dual-writing, keep using source"
- Catches bugs while still in low-stakes mode (source is still authoritative)

**Cons:**
- Requires application changes (sometimes substantial)
- Adds write latency (each write hits two systems)
- Inconsistency window — if source write succeeds but target fails, you have divergence
- Reconciliation logic is non-trivial — you need a plan for when target gets out of sync

**Workflow:**

1. Deploy code that writes to BOTH source and target. Target writes are best-effort initially
2. Run a backfill to bring target up-to-date with source's existing data
3. Start strict mode: target writes must succeed; if they fail, alert and reconcile
4. Run dual-write for a soak period (weeks)
5. Validate continuously — source and target should match
6. Switch reads from source to target one endpoint at a time
7. Once all reads are from target: stop writing to source (writes are now target-only)
8. Decommission source

See `dual-write-and-cdc.md` for the code patterns.

## CDC-based migration

A Change Data Capture tool reads the source's transaction log and replicates changes to Couchbase. No application code changes needed on the source side.

**When to use:**
- Zero downtime requirement
- You can't or won't modify application code
- Source has a CDC-compatible transaction log (most relational DBs, MongoDB oplog)
- You have ops capacity to run the CDC pipeline

**Pros:**
- Zero downtime
- No app code changes for the source
- Continuous sync — target stays current with source
- Works for systems where the source is third-party or hard to change

**Cons:**
- Setting up CDC tooling is non-trivial (Debezium + Kafka + sink connector is a real ops surface)
- CDC has its own failure modes (replication lag, dropped events, oplog rotation)
- Transformation in the pipeline is more constrained than in app code
- Eventual consistency window between source and target

**Common CDC tooling:**

| Tool | Sources | Notes |
|---|---|---|
| **Debezium** | Postgres, MySQL, MongoDB, Oracle, SQL Server | Most popular open-source CDC. Runs on Kafka Connect |
| **AWS DMS** | Most RDBMS sources | Managed service in AWS. **No first-party Couchbase target** — reaches Couchbase via Kafka or a file staging step. Verify AWS's current target list before designing around it |
| **Striim** | Many sources | Commercial; supports complex transformations |
| **Couchbase XDCR** | Only Couchbase-to-Couchbase | Built-in; for cluster-to-cluster migrations |
| **Custom Kafka pipeline** | Anything that writes to Kafka | Build your own |

Workflow is similar to dual-write but the "dual-write" is done by the CDC pipeline instead of application code.

## The decision flow

Walk through these in order:

```
Can you tolerate downtime?
├── Yes, hours of it
│   └── How big is the data?
│       ├── Small (< 100 GB) → BIG-BANG
│       └── Large → PHASED (slice it up)
└── No, zero downtime required
    └── Can you modify application code?
        ├── Yes → DUAL-WRITE
        └── No → CDC-BASED
```

Special case: if the application has clear slices AND you want zero downtime, consider per-slice big-bang within an overall phased approach. Each slice gets a short downtime for its cutover; the rest of the app keeps running.

## Combining strategies

Real migrations often combine approaches:

**Phased + big-bang per slice:** good for monoliths where each slice has its own scheduled maintenance window.

**Phased + dual-write per slice:** zero-downtime per slice but limited blast radius.

**Big-bang for backfill, then dual-write or CDC for ongoing:** common in CDC setups. The initial bulk load is "big-bang" (export source as of T0, import to target); CDC handles changes after T0.

## Anti-patterns

- **No backfill plan:** starting dual-write without backfilling existing data means target has only writes from "now" onward; reads will miss anything older
- **Validation deferred to "after cutover":** if you find divergence then, rolling back is much harder. Validate during transition
- **Source decommissioned on cutover day:** removes your rollback path. Keep source running, even read-only, for weeks
- **Dual-write without idempotency:** retries on transient failures create duplicates in target
- **"We'll skip staging":** the staging migration catches 80% of the bugs you'd otherwise hit in production
- **CDC pipeline as black box:** if no one on the team understands the CDC tool, problems become showstoppers

## Estimating effort

Rough planning numbers for a typical production migration:

| Approach | Engineering effort | Calendar time | Risk level |
|---|---|---|---|
| Big-bang, small data | 1-2 weeks | 2-4 weeks (incl. validation) | Medium |
| Phased, medium app | 2-3 months | 3-6 months | Low-medium |
| Dual-write, large app | 3-6 months | 4-9 months | Low if done carefully |
| CDC, complex pipeline | 2-4 months | 3-6 months | Medium (tooling risk) |

Set expectations early. Migration projects that get "we'll be done by Friday" framing are setting up for failure.

## Quick decision tree

- **Downtime OK + small data?** → big-bang
- **No downtime + can modify app?** → dual-write
- **No downtime + can't modify app?** → CDC
- **Large app with natural slices?** → phased
- **Unsure?** → answer the five questions in SKILL.md first; the right approach usually emerges
- **Picking a CDC tool?** → Debezium plus the Couchbase Kafka sink connector for the open-source path; AWS DMS only once you've confirmed how it will actually reach Couchbase (it has no first-party Couchbase target); commercial tooling if you need complex transformation — verify current Couchbase support with the vendor
- **Combining strategies?** → fine; common patterns are phased+big-bang or big-bang-backfill+CDC
