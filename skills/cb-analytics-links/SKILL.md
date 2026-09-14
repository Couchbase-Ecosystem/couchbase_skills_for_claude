---
name: cb-analytics-links
description: |
  Use this skill when the user is managing Analytics data-source links —
  S3, Azure Blob, GCS, remote Couchbase, or Kafka-pipeline links — including
  creating, updating, listing, or deleting them, and which sources each
  Analytics product actually supports. Trigger when they mention "S3 link",
  "Azure Blob", "GCS link", "remote Couchbase link", "external dataset",
  "data source", "create_link", or credentials for any of those.
license: Apache-2.0
---

# Managing Analytics links

A *link* in Analytics connects external storage so it can be queried as a
dataset. The 5 tools cover the lifecycle: list, get, create, update, delete.

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

## Link types and their config

### S3
```json
{
  "type": "s3",
  "region": "us-east-1",
  "accessKeyId": "AKIA...",
  "secretAccessKey": "...",
  "serviceEndpoint": "https://s3.example.com",   // optional (MinIO, etc.)
  "sessionToken": "..."                          // optional (STS)
}
```

### Azure Blob
```json
{
  "type": "azureblob",
  "accountName": "myacct",
  "accountKey": "...",                  // OR sharedAccessSignature
  "sharedAccessSignature": "?sv=...",
  "endpoint": "https://blob.example.com"   // optional
}
```

### GCS
```json
{
  "type": "gcs",
  "jsonCredentials": "{...full service account JSON...}",
  // OR
  "applicationDefaultCredentials": true,
  "endpoint": "https://storage.googleapis.com"  // optional
}
```

### Remote Couchbase
```json
{
  "type": "couchbase",
  "hostname": "remote.example.com",
  "username": "analytics",
  "password": "...",
  "encryption": "full",            // none | half | full
  "certificate": "-----BEGIN ...",
  "clientCertificate": "...",      // optional mTLS
  "clientKey": "..."
}
```

## What each product can actually connect to

The four config shapes above are what **this MCP server's `create_link` tool**
accepts against a Couchbase Server / Capella operational cluster. The wider
Analytics family supports more, and the differences matter — do not promise a
user a source their product does not have.

| Source | Capella Analytics | Enterprise Analytics |
|---|---|---|
| Amazon S3 (and S3-compatible) | Yes (cross-account trust auth added March 2026) | Yes (2.0+) |
| Azure Blob Storage | Yes (June 2026) | Yes (2.1+) |
| Google Cloud Storage | Yes (March 2025) | Yes (2.2+) |
| Remote Couchbase (Capella operational / Couchbase Server) | Yes | Yes |
| Kafka pipelines — **Confluent Cloud** and **Amazon MSK** | Yes | Yes (Confluent) |
| Delta Lake tables (read-only) | Yes (January 2025) | Yes |
| **Apache Iceberg tables** (read-only, via AWS Glue / BigLake Metastore catalogs) | **No — not documented** | **Yes, 2.2+ only** |

File formats for object-storage collections: JSON (JSON Lines), CSV, TSV,
Parquet, Avro, plus Delta (`"table-format": "delta"`) and, on Enterprise
Analytics 2.2+, Iceberg.

**CDC.** There is no first-party "CDC link" type. CDC arrives **through a Kafka
pipeline**: Enterprise Analytics 2.2 added documented CDC ingestion from
**Oracle** and **SQL Server** via Kafka and Debezium connectors. Capella
Analytics documents DynamoDB ingestion via a partner (MOLO17 Gluesync)
connector. Anything else — MySQL, PostgreSQL, MongoDB — is whatever the user's
Kafka connector emits, not a Couchbase-supported source; say that rather than
implying first-party support.

Sources:
`https://docs.couchbase.com/analytics/release-notes/release-notes.html`,
`https://docs.couchbase.com/enterprise-analytics/current/release-notes/release-notes.html`,
`https://docs.couchbase.com/analytics/sources/manage-remote.html`,
`https://docs.couchbase.com/analytics/sqlpp/5_ddl_external.html`

Note on where links are created: in Capella Analytics, external object-storage
links are created **through the UI**, not with SQL++ DDL — only the external
*collection* has DDL. Don't hand a user a `CREATE LINK` statement for S3/GCS/
Azure on that product.

## Credentials in audit logs

All of the above keys (accessKeyId, secretAccessKey, accountKey, jsonCredentials,
password, clientKey, etc.) are auto-redacted in the audit log. You can be
confident that passing credentials through `create_link` won't leave them in
the audit trail.

## Workflow

1. `list_links(dataverse="X")` — see what already exists; don't recreate.
   The `dataverse` argument names an **Analytics scope**: `DATAVERSE` is still
   valid DDL in the in-cluster Analytics Service and is documented as a synonym
   for `ANALYTICS SCOPE`. On Capella Analytics and Enterprise Analytics the
   user-facing hierarchy is **Database -> Scope -> Collection** and "dataverse"
   no longer appears in prose. Keep `dataverse` where it is the literal
   parameter name; say "Analytics scope" when talking to the user.
2. `create_link(name, dataverse, config)` — create new.
3. `get_link(name)` — verify the type and active datasets.
4. `update_link(name, config)` — rotate credentials without recreating the
   datasets that point to it.
5. `delete_link(name)` — safe only when no datasets reference it; otherwise
   it returns a `RequestError`.

## Naming convention

There is no Couchbase-documented naming convention for links. A readable
`<source>-<purpose>` pattern (`s3-events`, `azure-archive`, `cb-replica`) is a
reasonable default; follow whatever the user's existing links already do rather
than renaming to match a house style.

## What to avoid

- Don't put credentials in source control. Always upsert them via the tool
  at deploy time, or read from a secrets manager.
- Don't switch a link's `type` via update; delete and recreate instead.
- Don't rotate credentials by deleting + recreating — use `update_link` so
  existing datasets stay attached.

## Rate limits & safety

Link tools split across categories:

- **`read`** (60/sec): `list_links`, `get_link`.
- **`write`** (1/sec, intentional): `create_link`, `update_link`,
  `delete_link`.

Link mutations are destructive — deleting a link with attached datasets
breaks downstream queries; updating credentials wrong takes ingestion
offline. The 1/sec write limit is deliberately constraining. If you're
batch-creating links from a config file, sequence the calls and accept
the throttling.

If `RateLimitExceeded` comes back from a `create_link` / `update_link` /
`delete_link`, honour `retry_after_sec`. Don't retry-storm — sleep for
the indicated duration, then continue.

`list_links` and `get_link` share the global `read` bucket with every
other read-only tool on the server. In a "show me everything about the
link landscape" workflow, prefer one `list_links` plus targeted
`get_link` calls over polling.

## Related skills

- `cb-analytics-schema` — once a link is connected and datasets exist, use this to discover their field shapes
- `cb-analytics-query` — querying data that arrives via links
- `cb-analytics-mcp-setup` — configuring the MCP server credentials (S3/Azure/GCS keys go in env vars, not inline)
