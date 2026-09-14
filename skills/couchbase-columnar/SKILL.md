---
name: couchbase-columnar
description: "Design and use Couchbase Capella Analytics (the managed cloud service, formerly named Capella Columnar) and Couchbase Enterprise Analytics (the self-managed edition). Use whenever the user asks about Capella Analytics, Capella Columnar, columnar analytics, Enterprise Analytics, an Analytics cluster, Capella Analytics vs the embedded Analytics Service, Analytics databases scopes and collections, remote and external links, Kafka pipeline links, Delta Lake or Apache Iceberg access, Analytics SQL++, BI and JDBC connectivity, or 'I need to run analytical queries on my Couchbase data.' Distinct from the cb-analytics-* skills, which cover the Analytics Service embedded in Couchbase Server and Capella operational clusters. Use proactively when the user needs OLAP-scale analytics, BI tool integration, or columnar storage for analytical workloads."
license: Apache-2.0
---

# Couchbase Analytics (Capella Analytics and Enterprise Analytics)

A skill for *designing and using* Couchbase's standalone columnar analytical database, in both its managed and self-managed forms.

## Naming: "Capella Columnar" is retired

**Capella Columnar was formally rebranded to Capella Analytics in August 2025.** The Capella Analytics release notes state it plainly: *"Effective today, Capella Columnar has been formally rebranded as Capella Analytics. All relevant documentation and product references have been updated to reflect this change."* (https://docs.couchbase.com/analytics/release-notes/release-notes.html, August 2025 changelog)

Use these names:

| Name | What it is |
|---|---|
| **Capella Analytics** | The managed/cloud service on Capella. Formerly Capella Columnar. |
| **Couchbase Enterprise Analytics** | The self-managed / on-premises edition. Per its 2.0 release note it *"delivers the powerful capabilities seen in our cloud offering, Capella Analytics (formerly Capella Columnar), but in a new form that's optimized for on-premise and self-managed deployments."* (https://docs.couchbase.com/enterprise-analytics/current/release-notes/release-notes.html) |
| **the Analytics Service** | The service co-located on a Couchbase Server / Capella operational cluster. A different product — see the `cb-analytics-*` skills. |

This skill's directory is still named `couchbase-columnar` for stability; the word "columnar" survives in prose only where it describes the **storage format**, and in a handful of legacy identifiers (the Analytics SDK doc paths are still `java-columnar-sdk`, `nodejs-columnar-sdk`, `python-columnar-sdk`). Do not use "Capella Columnar" as a product name.

## Capella Analytics vs the embedded Analytics Service

| | Analytics Service (embedded) | Capella Analytics / Enterprise Analytics (standalone) |
|---|---|---|
| **What it is** | A Service on an operational cluster | A standalone analytical database cluster |
| **Where it runs** | Analytics nodes inside the operational cluster | Its own Capella Analytics cluster, or its own self-managed Enterprise Analytics cluster |
| **Storage** | Row-oriented shadow datasets on cluster storage | Column-oriented LSM + B-tree engine over **shared object storage**, with compute scaled independently |
| **Data ingestion** | DCP shadowing from the local cluster | Remote links (Capella / Server / Kafka), external links (S3, GCS, Azure Blob), standalone collections |
| **Best for** | Ad-hoc analytics alongside operational workloads | OLAP, BI tools, lakehouse queries, large analytical workloads isolated from production |
| **Skills** | `cb-analytics-*` | This skill |

## When this skill applies

- "What is Capella Analytics? What happened to Capella Columnar?"
- "Should I use standalone Capella Analytics or the embedded Analytics Service?"
- "Capella Analytics or Enterprise Analytics — which one do I want?"
- "How do I stream my Capella operational data into Analytics?"
- "How do I query S3 / GCS / Azure Blob / Delta Lake / Iceberg from Couchbase?"
- "How do I connect Tableau, Power BI, Superset, or a JDBC BI tool?"
- "How do I query JSON data with SQL++ in Analytics?"

## Pick the right reference

| Question | Read |
|---|---|
| "Architecture, data model, link types, Capella vs Enterprise vs embedded" | `references/architecture.md` |
| "Provisioning, connecting sources, querying, BI and JDBC connectivity" | `references/usage.md` |

## Core principle: this is OLAP, not OLTP

Capella Analytics and Enterprise Analytics are optimized for analytical queries — large scans, aggregations, `GROUP BY`, window functions, joins over large datasets. Neither replaces the operational cluster. Your application's transactional reads and writes still go to the operational cluster; Analytics receives data through links and stores it columnar for efficient analytical access. Analytics can write results *back* to the operational Data Service with `COPY TO` when an application needs them.

Because Analytics runs on its own cluster, heavy analytical queries do not compete with the operational workload for CPU, memory, or I/O. That isolation is the main production argument for the standalone product over the embedded Analytics Service.

## Related skills

- `cb-analytics-*` — the Analytics Service embedded in operational clusters (different product)
- `couchbase-capella` — provisioning the Capella operational cluster that Analytics links to
- `couchbase-sqlpp-tuning` — SQL++ patterns; note Analytics SQL++ has its own reference and its own differences
