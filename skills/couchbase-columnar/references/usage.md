# Analytics usage (Capella Analytics and Enterprise Analytics)

Verified against docs.couchbase.com and official Couchbase repositories in September 2026. Source URLs inline. Product names: **Capella Analytics** (managed) and **Couchbase Enterprise Analytics** (self-managed). "Capella Columnar" is retired.

## Contents

- [Provisioning a Capella Analytics cluster](#provisioning-a-capella-analytics-cluster)
- [Connecting to your operational cluster](#connecting-to-your-operational-cluster)
- [External data sources](#external-data-sources)
- [Querying with SQL++](#querying-with-sql)
- [Writing results out](#writing-results-out)
- [SDKs](#sdks)
- [BI tool connectivity](#bi-tool-connectivity)
- [JDBC](#jdbc)
- [Access control](#access-control)
- [Management API](#management-api)
- [Performance tips](#performance-tips)

## Provisioning a Capella Analytics cluster

In the Capella UI, go to the **Analytics** area of your organization and create a cluster inside a project. Source: https://docs.couchbase.com/analytics/admin/prepare-project.html

Settings to think about:

- **Compute and node configuration** — Analytics compute is sized separately from operational compute; storage is object storage and scales independently.
- **Cloud and region** — AWS, GCP, and (since June 2026) **Azure**. Put the Analytics cluster in the same region as the operational cluster it links to, to keep link latency and cross-region data transfer down.
- **Networking** — Analytics clusters have their own allowed-IP list, VPC/VNet peering (AWS, GCP, Azure), and private endpoints (AWS PrivateLink, Azure Private Endpoint). See https://docs.couchbase.com/analytics/admin/ip-allowed-list.html and the peering/private-connection pages under `analytics/admin/`.

There is **no free tier for Capella Analytics** — the Capella free tier covers Operational clusters only.

Analytics clusters can be turned off and on (https://docs.couchbase.com/analytics/admin/off-on.html) and backed up and restored (https://docs.couchbase.com/analytics/admin/backup-restore.html).

For **Enterprise Analytics**, you install and run the cluster yourself; start at https://docs.couchbase.com/enterprise-analytics/current/intro/start-here.html

## Connecting to your operational cluster

Streaming from a Couchbase source uses a **remote link** plus **remote collections**:

1. In the Analytics UI, add a remote data source — **Couchbase Capella** or **Couchbase Server**. (https://docs.couchbase.com/analytics/sources/remote-cb-capella.html, https://docs.couchbase.com/analytics/sources/remote-cb-server.html)
2. Supply connection and credential details; the link stores them.
3. Create remote collections against the link for the operational collections you want shadowed, optionally with data filters.
4. **Connect** the link. While connected it streams continuously and the shadow copy stays close to live. Disconnecting freezes the collection at its last state.

You can also create these with SQL++ — `CREATE COLLECTION ... ON`/`AT` for a remote collection (https://docs.couchbase.com/analytics/sqlpp/5_ddl_remote.html), then `CONNECT LINK` / `DISCONNECT LINK`.

For Kafka sources (Confluent Cloud, Amazon MSK, and Debezium/GlueSync CDC from MongoDB, MySQL, PostgreSQL, DynamoDB, Oracle, SQL Server), create a **Kafka pipeline link** and then a **Kafka pipeline collection**. (https://docs.couchbase.com/analytics/sources/remote-kafka.html, https://docs.couchbase.com/analytics/sources/kafka-collection.html)

## External data sources

External links let you query object storage in place — no ingestion, no copy. Create an **external link** then an **external collection** over it.

| Store | Setup doc |
|---|---|
| Amazon S3 | https://docs.couchbase.com/analytics/sources/setup-aws-s3-external-source.html |
| Google Cloud Storage | https://docs.couchbase.com/analytics/sources/setup-gcs-external-source.html |
| Azure Blob Storage | https://docs.couchbase.com/analytics/sources/setup-azure-blob-external-source.html |

Readable formats: **JSON, CSV, TSV, Parquet, Avro**, plus read-only **Delta Lake** tables. On **Enterprise Analytics 2.2 and later** only, read-only **Apache Iceberg** tables via registered catalogs (AWS Glue, BigLake Metastore) — see `CREATE CATALOG` and `CREATE EXTERNAL COLLECTION` on a catalog (https://docs.couchbase.com/enterprise-analytics/current/sqlpp/5_ddl_iceberg.html). Iceberg has not been announced for Capella Analytics as of September 2026.

**External collections cannot be indexed** — every query reads from the object store. Use a location path / dynamic prefix layout so queries prune whole prefixes (https://docs.couchbase.com/analytics/sources/dynamic-prefixes.html).

For the exact IAM permissions each store needs, see the "Cloud Read/Write Permissions" / "Required Permissions" pages alongside each setup doc.

## Querying with SQL++

Analytics uses **SQL++**, with its own reference at https://docs.couchbase.com/analytics/sqlpp/1_intro.html. Reference collections as `database.scope.collection`.

```sql
-- Aggregation
SELECT category, COUNT(*) AS cnt, AVG(price) AS avg_price
FROM Default.shop.products
GROUP BY category
ORDER BY cnt DESC;
```

```sql
-- Window function
SELECT
    order_id,
    customer_id,
    total,
    SUM(total) OVER (PARTITION BY customer_id ORDER BY created_at) AS running_total
FROM Default.orders.completed;
```

```sql
-- Join across collections
SELECT o.order_id, c.name AS customer_name,
       SUM(oi.quantity * oi.price) AS order_total
FROM Default.orders.orders AS o
JOIN Default.customers.profiles AS c ON o.customer_id = c.id
JOIN Default.orders.order_items AS oi ON oi.order_id = o.order_id
GROUP BY o.order_id, c.name;
```

Available DDL/DML includes `CREATE DATABASE`, `CREATE SCOPE`, `CREATE COLLECTION` (remote / external / standalone), `CREATE SYNONYM`, `CREATE INDEX`, `CREATE VIEW`, `INSERT`, `UPSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `COPY INTO`, and `COPY TO`.

Version gates worth knowing:

- **`UPDATE`** arrived in **August 2026** for Capella Analytics and in **Enterprise Analytics 2.2**. On Capella Analytics it applies to standalone collections; on Enterprise Analytics 2.2 the release note says standalone *and remote* collections.
- **Index-only query plans** (serving a query entirely from a covering index) arrived in the same wave.
- **Heterogeneous indexes** — indexes no longer require a single declared data type — arrived October 2025 for Capella Analytics. Mixing heterogeneous fields with schema-declared fields in one index definition is not supported.
- **Unlimited columns** and **UDF-based transformation during ingestion** also landed October 2025.
- Enterprise Analytics 2.2 adds an **Index Advisor** that recommends secondary indexes for a query.

## Writing results out

- **`COPY TO` an external data store** — export query results to S3, GCS, or Azure Blob as **JSON**, **CSV**, or **Parquet**. (https://docs.couchbase.com/analytics/sqlpp/5_dml_copy_to_external.html) CSV and Parquet export arrived May 2025; JSON predates it.
- **`COPY TO` the Couchbase Data Service** — write results back into an operational collection so applications can serve them. (https://docs.couchbase.com/analytics/sqlpp/5_dml_copy_to_kv.html)
- **Views and Tabular Analytics Views (TAVs)** — the SQL-shaped surface BI tools consume. (https://docs.couchbase.com/analytics/sqlpp/5a_views.html)

## SDKs

Analytics SDKs exist for **Java, Node.js, and Python**. Their documentation paths still carry the legacy `columnar` token (`java-columnar-sdk`, `nodejs-columnar-sdk`, `python-columnar-sdk`) — that is a URL artifact of the rebrand, not a current product name. Index: https://docs.couchbase.com/home/columnar-sdk.html

## BI tool connectivity

The documented path is: **create a tabular view (TAV) over your collections or query results, then point the BI connector at it.** Source: https://docs.couchbase.com/analytics/query/bi.html

| Tool | Connector | Support model |
|---|---|---|
| **Tableau** | Couchbase Tableau Connector — **version 1.1.3 or later** is required for Analytics | Couchbase officially supported |
| **Power BI** | Couchbase Power BI Connector (Desktop and Service; import and DirectQuery modes) | Couchbase officially supported |
| **Apache Superset** | Couchbase Superset Connector, over SQLAlchemy (`github.com/couchbase/couchbase-sqlalchemy`) | Couchbase officially supported |
| **Looker Studio** | Couchbase Looker Studio connector (`github.com/Couchbase-Ecosystem/couchbase-gcp-lookerstudio-connector`), via the Data API | Couchbase **community** supported |
| Any generic JDBC BI tool | Couchbase JDBC driver — see below | Couchbase **community** supported |

When reading the Tableau connector docs against Analytics: references to "Couchbase Server" apply to Analytics too, and you skip the steps about enabling the Analytics Service.

Source for the support-model column: https://docs.couchbase.com/analytics/query/integration.html

## JDBC

The repo previously carried an unverified JDBC URL string. Resolved.

The driver is the open-source, **read-only** Couchbase JDBC driver at **https://github.com/couchbaselabs/couchbase-jdbc-driver**, listed in the Couchbase integrations table as **community supported**.

Per its README, the URL prefix is:

```
jdbc:couchbase:analytics://<host>/<databaseName>/<scopeName>[?property1=value1[&property2=value2]...]
```

`jdbc:cb:analytics` is accepted as a fallback prefix. Example from the README:

```
jdbc:couchbase:analytics://127.0.0.1/foo/bar
```

Do **not** use `jdbc:couchbase-analytics://` — that form circulates in older material and is not the driver's scheme. Check the repository README for the current property list before hardcoding connection properties, and prefer the first-party Tableau / Power BI / Superset connectors where one exists for your tool.

## Access control

Capella Analytics has its own RBAC, introduced March 2025: roles and privileges for granular, programmatic data access, plus **Access Control Accounts** for service-to-service access that are not tied to an individual user. UI tools such as the Workbench use separate controls. Source: https://docs.couchbase.com/analytics/admin/auth/auth-data.html

Enterprise Analytics 2.2 adds **JWT authentication**, including tokens from external identity providers, and can grant Analytics RBAC roles to external users without a local Couchbase account.

## Management API

Capella Analytics has its own Management API guide and reference under https://docs.couchbase.com/analytics/management-api-guide/management-api-intro.html, sharing the Capella Management API v4 surface and the `https://cloudapi.cloud.couchbase.com` base URL.

## Performance tips

**Lay out object storage so prefixes prune.** External collections cannot be indexed, so scan reduction comes entirely from the location path. Partition by date components (year, month, day) and query with predicates that match the prefix structure.

**Index remote and standalone collections.** Only these two collection types support indexes. Since October 2025 indexes may be heterogeneous (no single declared type), and since August 2026 a covering index can serve a query with an index-only plan.

**Avoid `SELECT *`.** The whole point of columnar storage is reading only the referenced columns; `SELECT *` forfeits that.

**Let the cost-based optimizer work.** It samples rather than scanning to estimate statistics. If plans look wrong, capture the plan from the Workbench (**View Query Metrics or Plan**) before hand-tuning.

**Scale compute for concurrency, not capacity.** Storage is object storage and scales on its own; add compute when query concurrency or aggregate scan throughput is the bottleneck.

**Disconnect idle remote links.** A connected remote link streams continuously and is a billable, resource-consuming state; disconnect it when a dataset does not need to stay live. Turning the whole Analytics cluster off is also supported for non-continuous workloads.
