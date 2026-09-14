---
name: cb-analytics-schema
description: |
  Use this skill when the user wants to inspect, discover, or document the
  structure of Couchbase Analytics scopes (dataverses) and collections — listing what
  exists, inferring document shapes, or building a data dictionary. Trigger
  when they mention "schema", "dataverses", "Analytics scopes", "datasets", "what fields are in",
  "what's the structure of", "infer_schema", or "Metadata.\`Dataverse\`".
license: Apache-2.0
---

# Schema introspection

Three tools cover dataset discovery:

- `list_dataverses(cluster)` — every Analytics scope in metadata
- `list_datasets(dataverse, cluster)` — Analytics collections, optionally
  scoped to one Analytics scope
- `infer_schema(dataset, sample_size, cluster)` — sample N docs, summarise
  observed top-level fields

## Which "Analytics" this skill covers

The tools in this skill talk to the **Analytics Service running inside a
Couchbase Server or Capella operational cluster** (the `cbas` service). That
service still ships in Couchbase Server 8.0.

Two *separate* Couchbase products also carry the Analytics name. Their tool
surface, RBAC roles, and namespace terms differ from what is documented below,
so if the user is on one of them, say so rather than guessing:

| Product | What it is | Docs |
|---|---|---|
| **Capella Analytics** | Couchbase's managed analytical database (RT-OLAP). **Renamed from "Capella Columnar" in August 2025** — "Capella Columnar" is a retired name; do not use it. | `https://docs.couchbase.com/analytics/` |
| **Couchbase Enterprise Analytics** | The self-managed/on-prem standalone analytical database. 2.0 GA August 2025; **2.2 is current** (2.2.1 July 2026). | `https://docs.couchbase.com/enterprise-analytics/current/` |

These are different deployments of a related capability, not synonyms for each
other and not synonyms for the in-cluster Analytics Service.

Sources: Capella Analytics release notes
(`https://docs.couchbase.com/analytics/release-notes/release-notes.html`) —
"Effective today, Capella Columnar has been formally rebranded as Capella
Analytics."; Enterprise Analytics release notes
(`https://docs.couchbase.com/enterprise-analytics/current/release-notes/release-notes.html`).

## Inferring a useful schema

`infer_schema` reads up to `sample_size` documents (default 100) and
returns:

```json
{
  "dataset": "Default.Users",
  "rows_sampled": 100,
  "fields": {
    "id":         {"present_count": 100, "presence_pct": 100.0, "types": ["str"]},
    "name":       {"present_count": 100, "presence_pct": 100.0, "types": ["str"]},
    "age":        {"present_count":  87, "presence_pct":  87.0, "types": ["int"]},
    "addresses":  {"present_count":  62, "presence_pct":  62.0, "types": ["list"]}
  }
}
```

Notes:

- The sample is **unordered**; don't infer cardinality or ordering from it.
- A field with `presence_pct < 100` is optional in the dataset.
- Multiple entries in `types` mean the dataset is heterogeneous — flag this
  to the user.

## Namespace and metadata names

The tool names say "dataverse" because that is what the in-cluster Analytics
Service calls it in DDL and metadata — and it still does: `DATAVERSE` is
documented as a **synonym for `ANALYTICS SCOPE`**, and the metadata collections
live in the `Metadata` Analytics scope as ``Dataverse``, ``Dataset``,
``Synonym``, ``Index``, ``Function`` and ``Link`` (so
``Metadata.`Dataverse` `` is correct here). Source:
`https://docs.couchbase.com/server/current/analytics/5_ddl.html`

On **Capella Analytics** and **Enterprise Analytics** the documented hierarchy
is **Cluster -> Database -> Scope -> Collection**, "dataverse" is gone from
user-facing prose, and metadata lives under `System.Metadata` with
``Database``, ``Dataverse`` (which holds *scope* metadata), ``Dataset`` (which
holds *collection* metadata), ``Function``, ``Index``, ``Link`` and
``Synonym``. Sources:
`https://docs.couchbase.com/analytics/sources/database-objects.html`,
`https://docs.couchbase.com/analytics/sqlpp/5_ddl_metadata.html`

None of these are the Data service's Bucket -> Scope -> Collection. An
Analytics collection may mirror a Data service collection through a link, but
it is a separate object. When you present a data dictionary, label which
hierarchy you are describing.

## Safety

The dataset name is interpolated into a SQL++ FROM clause because SQL++
doesn't support parameterised identifiers. The server validates the name
with a strict regex first; you don't need to worry about escaping. Names
like `Default.\`my dataset\`.sub` (backtick-quoted) are accepted.

## Building a data dictionary

A typical workflow:

1. `list_dataverses` → choose one
2. `list_datasets(dataverse="X")` → enumerate datasets
3. For each, `infer_schema(dataset="X.Y", sample_size=500)` → table of fields
4. Optionally `execute_query_readonly` with `SELECT VALUE COUNT(*) FROM X.Y`
   to add a row count to each entry

## What to avoid

- Don't call `infer_schema` with a large `sample_size` — it runs a `SELECT`
  that scans that many documents, so cost scales with the sample. Start at the
  default 100 and only raise it if the shape looks under-sampled.
- Don't assume the sample covers every variant of the document shape.
  Treat `infer_schema` output as a starting point, not a contract.

## Rate limits & safety

Schema tools split across two rate-limit categories:

- **`read`** (60/sec): `list_dataverses`, `list_datasets`.
- **`query`** (10/sec): `infer_schema`.

`infer_schema` is `query` category — not `read` — because under the hood
it runs a `SELECT` that scans a sample of documents from the dataset.
That makes it relatively expensive and it shares the **same 10/sec
bucket as every other query tool** (`execute_query`,
`execute_query_readonly`, `execute_query_paginated`, `fetch_next_page`,
`explain_query`).

Practical implication: if you're enumerating schemas across many
datasets, you'll hit the query bucket faster than the read bucket.
Recommended pattern: one `list_dataverses` → one `list_datasets` per
dataverse (read budget) → then `infer_schema` calls spaced ≥ 100ms
apart (query budget).

If `RateLimitExceeded` comes back on an `infer_schema`, the bucket is
probably being shared with concurrent `execute_query*` calls. Honour
`retry_after_sec` and back off.

## Related skills

- `cb-analytics-query` — writing and running SQL++ queries against the discovered datasets
- `couchbase-data-modeling` — document shape, field naming, and embedding decisions (server-side modeling)
- `cb-analytics-links` — creating the links whose external datasets then appear in schema discovery
