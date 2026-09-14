# Analytics architecture (Capella Analytics and Enterprise Analytics)

Verified against docs.couchbase.com in September 2026. Source URLs inline. "columnar" below refers to the storage format; the products are **Capella Analytics** (managed) and **Couchbase Enterprise Analytics** (self-managed). "Capella Columnar" is a retired name — see the skill's SKILL.md for the rebrand citation.

## Contents

- [What the product is](#what-the-product-is)
- [Data model: Cluster → Database → Scope → Collection](#data-model-cluster--database--scope--collection)
- [Collection types](#collection-types)
- [Links: how data gets in](#links-how-data-gets-in)
- [Capella Analytics vs Enterprise Analytics](#capella-analytics-vs-enterprise-analytics)
- [Choosing between standalone Analytics and the embedded Analytics Service](#choosing-between-standalone-analytics-and-the-embedded-analytics-service)
- [Isolation and performance](#isolation-and-performance)

## What the product is

Capella Analytics is described by Couchbase as *"a JSON-native NoSQL analytical database with GenAI capabilities"* (https://docs.couchbase.com/analytics/intro/intro.html). Enterprise Analytics is *"a self-managed, JSON-native NoSQL analytical database"* (https://docs.couchbase.com/enterprise-analytics/current/intro/intro.html). They share an architecture:

- A **column-oriented storage engine** combining Log-Structured Merge (LSM) trees with B-trees. LSM gives high write throughput for ingestion; columnar layout accelerates analytical scans by reading only referenced columns.
- **Shared object storage** with **shared-nothing compute**. Data lives in cloud object storage; compute scales independently of storage.
- An **MPP query engine** with a sample-based **cost-based optimizer** that estimates statistics from a subset of data rather than scanning everything.
- **Zero ETL** ingestion: JSON is analyzed natively, no flattening step.
- SQL++ as the query language, with its own reference (https://docs.couchbase.com/analytics/sqlpp/1_intro.html).

## Data model: Cluster → Database → Scope → Collection

This is the biggest practical difference from the operational cluster's Bucket → Scope → Collection. Source: https://docs.couchbase.com/analytics/sources/database-objects.html

- **Cluster** — the Analytics deployment, created inside a Capella project (or installed, for Enterprise Analytics).
- **Database** — the top-level container within a cluster. Creating a cluster creates a database named `Default`. Add more with the UI or `CREATE DATABASE`.
- **Scope** — groups collections, indexes, links, and functions within a database. A scope named `Default` is created in `Default`. Scope names are unique within a database.
- **Collection** — holds the data you query. Collection names are unique within a scope.

Alongside collections, within a database and scope, you also create **views and tabular views**, **synonyms**, **user-defined functions**, and **indexes**.

**Links sit outside the database/scope/collection hierarchy** and are referenced by the collections that use them. One link can back many collections across scopes.

## Collection types

| Type | Data location | Indexable | Created with |
|---|---|---|---|
| **Remote collection** | Local shadow copy, streamed continuously from a remote source via a link | Yes | UI, or `CREATE COLLECTION` (remote form) |
| **External collection** | Stays in object storage; read on every query | **No** | UI, or `CREATE EXTERNAL COLLECTION` |
| **Standalone collection** | Local, populated by you | Yes | UI, or `CREATE COLLECTION` (standalone form) |

Remote collections keep whatever they had when the link was last disconnected. Standalone collections use no link and are filled by import, `INSERT`, `UPSERT`, or `COPY INTO`.

## Links: how data gets in

Analytics does not take direct application writes. Data arrives through **links**, which hold credentials and connection details.

**Remote links** have connected/disconnected states and stream continuously when connected:

| Remote source | Notes |
|---|---|
| **Couchbase Capella operational cluster** | Managed streaming of collections into remote collections |
| **Couchbase Server** (self-managed) | Same shape, against a self-managed cluster |
| **Kafka pipeline link** | Confluent Cloud Kafka and Amazon MSK. Officially supported. |

Over a Kafka pipeline link, Couchbase documents officially supported CDC sources: **MongoDB**, **MySQL** (Debezium), **PostgreSQL** (Debezium), **DynamoDB** (GlueSync), and — added in **August 2026** for Capella Analytics and **Enterprise Analytics 2.2** — **Oracle** and **SQL Server** via Debezium. Sources: https://docs.couchbase.com/analytics/query/integration.html, https://docs.couchbase.com/analytics/release-notes/release-notes.html

**External links** have no connected state; each query reads through to the store:

| External source | Capella Analytics | Enterprise Analytics |
|---|---|---|
| **Amazon S3** | Yes (since launch). Cross-account trust authentication added March 2026. | Yes |
| **Google Cloud Storage (GCS)** | Yes (March 2025) | Yes (2.2, June 2026) — also usable as the deployment's underlying storage layer |
| **Azure Blob Storage** | Yes (June 2026, with Azure availability) | Yes |
| **Delta Lake tables** | Read-only (January 2025, on S3) | Read-only |
| **Apache Iceberg tables** | **Not announced for Capella Analytics as of September 2026** | **Yes — Enterprise Analytics 2.2 (June 2026)**, read-only, via registered catalogs such as AWS Glue and BigLake Metastore |

File formats readable from object storage: **JSON, CSV, TSV, Parquet, Avro** (plus Delta tables, and Iceberg tables on Enterprise Analytics). `COPY TO` exports query results back to object storage as **JSON, CSV, or Parquet**, and `COPY TO` against the Couchbase Data Service writes results back to an operational collection.

## Capella Analytics vs Enterprise Analytics

| | Capella Analytics | Couchbase Enterprise Analytics |
|---|---|---|
| Deployment | Managed service on Capella | Self-managed, on-prem or your own cloud |
| Current version line | Continuous delivery; changes tracked in the monthly changelog | **2.2** (June 2026); **2.2.1** maintenance (July 2026). 2.1 was November 2025; 2.0 was the August 2025 launch. |
| Clouds | AWS, GCP, and **Azure** (June 2026, initially Sweden Central, expanding) | Wherever you install it; S3, GCS, and Azure Blob supported as storage |
| Free tier | **No** — the Capella free tier is Operational only | n/a |
| Apache Iceberg | Not announced as of September 2026 | 2.2, read-only via catalogs |
| Notable 2.2-only features | — | JWT authentication, asynchronous REST query API, Index Advisor |
| Shared with Capella Analytics in 2026 | Index-only query plans, SQL++ `UPDATE`, Oracle/SQL Server CDC | Same, in 2.2 |

Release notes: https://docs.couchbase.com/analytics/release-notes/release-notes.html (Capella Analytics) and https://docs.couchbase.com/enterprise-analytics/current/release-notes/release-notes.html (Enterprise Analytics).

Enterprise Analytics 2.2 has a documented **known issue**: `request_plus` scan-consistency queries can hang (MB-72484). Check the release notes before relying on `request_plus` there.

## Choosing between standalone Analytics and the embedded Analytics Service

Use the **embedded Analytics Service** (`cb-analytics-*` skills) when:

- Your analytical queries run alongside the operational workload and sharing nodes is acceptable.
- You need analytics on a single operational cluster with minimal extra infrastructure.
- Analytical query volume is moderate.

Use **standalone Capella Analytics or Enterprise Analytics** when:

- You need columnar storage and MPP execution for large-scale analytical performance.
- Isolating heavy analytical queries from the operational cluster matters.
- You want BI tool connectivity through the Couchbase Tableau / Power BI / Superset connectors or a JDBC driver.
- You need to combine sources — operational Couchbase plus Kafka CDC plus object storage — in one query surface.
- You are building a data warehouse, data mart, or lakehouse over operational data.

Choose **Enterprise Analytics** specifically when the deployment must be self-managed or on-premises, or when you need Iceberg catalogs today.

## Isolation and performance

Because the Analytics cluster is separate, analytical queries do not compete with the operational workload for CPU, memory, or disk I/O — no noisy-neighbour effect on application response time. Compute and storage scale independently, so you can size the Analytics cluster for query concurrency without over-provisioning storage, and turn it off when idle.
