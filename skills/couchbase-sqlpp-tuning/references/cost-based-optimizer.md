# Cost-based optimizer, hints, and statistics

## Contents

- [Availability and edition](#availability-and-edition)
- [What CBO does and doesn't do](#what-cbo-does-and-doesnt-do)
- [Turning CBO on and off](#turning-cbo-on-and-off)
- [Verifying CBO ran](#verifying-cbo-ran)
- [Statistics — the prerequisite](#statistics--the-prerequisite)
- [Auto Update Statistics (8.0+ EE)](#auto-update-statistics-80-ee)
- [Optimizer hints](#optimizer-hints)
- [The USE clause](#the-use-clause)
- [Hints vs fixing the underlying problem](#hints-vs-fixing-the-underlying-problem)
- [Analytics has its own parameters](#analytics-has-its-own-parameters)
- [Verifying an improvement](#verifying-an-improvement)

## Availability and edition

The cost-based optimizer (CBO) is **Enterprise Edition only — not available in Community Edition**, and is available on Capella. It appeared as a developer preview in Couchbase Server 6.5 and has been part of the Query service through the 7.x and 8.x lines.

Two later changes matter for tuning:

- **7.6+** — the Query service gathers statistics automatically whenever an index is created or built.
- **8.0+** — *Auto Update Statistics* (AUS) can refresh stale statistics on a schedule. It is **opt-in and disabled by default**.

CBO does not replace the rule-based logic; it augments it where statistics make a better choice possible.

## What CBO does and doesn't do

Does:
- Estimates the cost of alternative join orders and access methods from statistics on indexes and collections
- Picks the cheaper plan when several equivalent plans exist
- Chooses between nested-loop and hash joins based on estimated cardinality

Doesn't:
- Help at all when statistics are missing or stale — it falls back to rule-based behaviour
- Invent an index. If no index serves the predicate, no optimizer will save the query
- Change the fact that hash joins are Enterprise Edition only

## Turning CBO on and off

Three levels, each with its own setting name:

| Level | Setting | Default |
|---|---|---|
| Request | `use_cbo` | inherits node setting |
| Node | `use-cbo` | `true` |
| Cluster | `queryUseCBO` | `true` |

It can also be set through Query Settings in the Couchbase Web Console.

```sql
-- Disable for a single request (request-level parameter)
SET use_cbo = false;
```

Generally, don't disable it. When CBO picks wrong, fix the statistics or add a hint rather than turning the whole thing off for everything.

## Verifying CBO ran

Two quick checks:

1. The plan carries `optimizer_estimates` blocks on operators when CBO ran:

```json
{
  "#operator": "IndexScan3",
  "index": "idx_a_field",
  "optimizer_estimates": {
    "cardinality": 24024,
    "cost": 4108.6,
    "fr_cost": 12.17,
    "size": 11
  }
}
```

2. `system:completed_requests` has a `useCBO` field per request. If it is false for the statement you care about, the problem is CBO not running, not CBO choosing badly.

If `optimizer_estimates` is absent, CBO either was disabled or had no statistics to work with.

## Statistics — the prerequisite

Statistics are collected with `UPDATE STATISTICS` (Enterprise Edition). It collects statistics on expressions over a named keyspace:

```sql
UPDATE STATISTICS FOR `travel-sample`.inventory.hotel(state, city, name);
```

There are also forms that target a named index, a list of indexes, and a DELETE form for removing statistics. See the SQL++ reference for the exact grammar of each variant.

Symptoms of missing or stale statistics:
- `optimizer_estimates` absent from the plan, or wildly wrong cardinalities
- The plan is identical to what the rule-based optimizer would produce
- Joins are always nested-loop, because a hash join needs cardinality information to be chosen

In production: on 7.6+ index creation seeds the statistics for you, but they go stale as data changes. Refresh them after large loads, and either enable AUS (8.0+ EE) or schedule `UPDATE STATISTICS` yourself. **`UPDATE STATISTICS` is a write — get the user's explicit approval before running it, and expect it to consume Query and Index service resources while it runs.**

## Auto Update Statistics (8.0+ EE)

AUS identifies outdated statistics and refreshes them on a schedule. It requires **Couchbase Server 8.0 or later, Enterprise Edition, with every query node at 8.0+**, and it is **disabled by default**.

Configuration lives in two system catalogs:

| Catalog | Purpose |
|---|---|
| `system:aus` | Global settings: `enable`, `schedule` (days, start/end time, timezone), `change_percentage` (the data-change threshold, 0-100, that marks statistics stale), `all_buckets`, `create_missing_statistics` |
| `system:aus_settings` | Per-bucket / per-scope / per-collection overrides, inherited hierarchically from the cluster down |

Reading these requires the `query_system_catalog` role; changing them requires `query_manage_system_catalog`.

Practical guidance: schedule AUS in a quiet window, because refreshing statistics is real work on a large collection. Set `create_missing_statistics` if you want AUS to seed statistics for indexed expressions that never had any. Don't assume AUS is on just because the cluster is 8.0 — check `system:aus` first.

## Optimizer hints

Hints (7.6+) live in a specially formatted comment. Two comment forms:

```sql
/*+ hint */     -- block form
--+ hint        -- line form
```

The `+` immediately after the comment opener is what marks it as a hint. Each hint can be written in a simple form or a JSON form.

### Query block hints

There is exactly one, and it goes in the SELECT clause:

| Hint | Simple form | JSON form | Effect |
|---|---|---|---|
| `ORDERED` | `ORDERED` | `{"ordered": true}` | Join the keyspaces in the order written in the query; the optimizer will not reorder them |

```sql
SELECT /*+ ORDERED */ u.name, o.total
FROM users u
INNER JOIN orders o ON o.user_id = u.id
WHERE u.status = 'admin';
```

### Keyspace hints

| Hint | Simple form | Notes |
|---|---|---|
| `INDEX` | `INDEX(keyspace index...)` | Consider these secondary indexes |
| `INDEX_ALL` (alias `INDEX_COMBINE`) | `INDEX_ALL(keyspace index index...)` | Requires at least two indexes; performs an intersect scan across all of them |
| `INDEX_FTS` | `INDEX_FTS(keyspace index...)` | Consider these full-text indexes |
| `USE_NL` | `USE_NL(keyspace...)` | Nested-loop join for the right-hand keyspace |
| `USE_HASH` | `USE_HASH(keyspace/BUILD)` or `USE_HASH(keyspace/PROBE)` | Hash join. **Enterprise Edition only** — silently ignored in Community Edition |

`/BUILD` makes the named keyspace the build side; `/PROBE` makes it the probe side; omitting the suffix lets the optimizer decide from estimated cardinality.

```sql
SELECT /*+ INDEX(hotel idx_state_city_cover) */ name, country
FROM `travel-sample`.inventory.hotel AS hotel
WHERE state = 'CA' AND city = 'Berkeley';
```

There are also negative keyspace hints (to exclude an index or join method) documented alongside the positive ones — check the SQL++ reference for your release before using them.

## The USE clause

Separate from hint comments, the `USE` clause attaches directly to a keyspace in the FROM clause:

- `USE KEYS expr` — fetch specific documents by key, skipping index selection entirely. The fastest possible access path when you know the keys.
- `USE INDEX (index-ref [, ...])` — restrict index selection to the named GSI or FTS indexes.

For ANSI joins, `USE HASH(BUILD)`, `USE HASH(PROBE)` and `USE NL` can be attached to the right-hand side of the join. You can combine one join method (`USE HASH` or `USE NL`) with one of `USE INDEX` or `USE KEYS`, but not two of the same kind.

The comment-hint forms and the USE clause overlap. Prefer the hint comments in new code: they cover more cases and they don't change the shape of the FROM clause.

## Hints vs fixing the underlying problem

Hints are duct tape. They work, but they embed implementation knowledge in the query, they drift as data changes, and they make queries harder to maintain.

Prefer fixing the root cause:

| Symptom | Real fix |
|---|---|
| Wrong index picked | Restructure the index keys, or collect statistics so CBO can tell them apart |
| Wrong join order | Collect statistics; check that both join keys are indexed |
| Statistics stale | Enable AUS (8.0+ EE) or schedule `UPDATE STATISTICS` |
| No index qualifies | Design one — see `index-design.md` |

Use a hint when you have confirmed via EXPLAIN that the forced plan is genuinely better, when the problem is transient (a migration window where statistics are temporarily wrong), or when one critical query needs a pinned, predictable plan.

## Analytics has its own parameters

The Analytics service is separate from the Query service and has its own compiler parameters, set per request. They do not affect correctness, only performance, and they do not persist.

```sql
SET `compiler.parallelism` = 4;
SET `compiler.queryplanshape` = "zigzag";
```

| Parameter | Effect |
|---|---|
| `compiler.parallelism` | Degree of parallelism for query execution |
| `compiler.queryplanshape` | Hash-join plan shape: `zigzag`, `leftdeep`, `rightdeep` |
| `compiler.sort.parallel` | Full parallel sort, or merge on one node |
| `compiler.framesize` | Frame size for buffered operators |

Naming note: the in-cluster **Analytics service** ships with Couchbase Server Enterprise Edition. The standalone products are **Capella Analytics** (cloud) and **Couchbase Enterprise Analytics** (self-managed); the name "Capella Columnar" is retired. None of these use the Query service's CBO — the parameters above are a separate mechanism.

## Verifying an improvement

1. Run the query with `profile` set to `timings` and capture `kernTime` / `servTime` / `execTime` per operator
2. Make one change — collect statistics, add a hint, or restructure the index
3. Re-run with profiling
4. Compare total runtime **and** per-operator timings. A faster total that just trades one slow operator for another is not a real win, and will regress as data grows

Change one thing at a time. Two simultaneous changes tell you nothing about which one helped.

## What to do next

- Non-join query, or a cluster without CBO → `query-patterns.md` and `index-design.md`
- Diagnosing a slow join → `joins-and-cbo.md`
- Wiring this into a workflow → `diagnostic-workflow.md`
