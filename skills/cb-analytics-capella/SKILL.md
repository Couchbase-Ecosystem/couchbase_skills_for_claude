---
name: cb-analytics-capella
description: |
  Use this skill when the user wants to manage Couchbase Capella resources
  through the Cloud Management API — listing organisations and clusters,
  provisioning or deleting clusters, triggering and restoring backups, or
  auditing API keys. Trigger when they mention "Capella", "cloud cluster",
  "capella_*", "organization", "project", "backup", "restore", or the
  Capella v4 API.
license: Apache-2.0
---

# Capella Management via cb-analytics-mcp

The 9 `capella_*` tools wrap Couchbase Capella's v4 Management API. They are
only available when `CB_CAPELLA_API_KEY_SECRET` is set; otherwise the tools
raise a clear `RuntimeError: Capella client is not configured`.

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

## The hierarchy

```
Organization (you may belong to several)
└── Project        (group of clusters; usually one per environment)
    └── Cluster    (the actual Capella deployment)
        └── Backup
```

Every cluster-scoped tool takes `(org_id, project_id, cluster_id)` in that
order. Use `capella_list_organizations()` and your own org's project IDs to
discover them — the tools don't accept names.

## Read-only first

- `capella_list_organizations()` — first call to discover IDs.
- `capella_list_clusters(org_id, project_id)` — see what exists.
- `capella_get_cluster(org_id, project_id, cluster_id)` — full details for one.
- `capella_list_backups(org_id, project_id, cluster_id)` — list available
  backups.
- `capella_list_api_keys(org_id)` — audit API key usage.

## Write operations (require confirmation)

- `capella_create_cluster(org_id, project_id, cluster_spec)` — `cluster_spec`
  is a free-form dict matching the v4 API schema; **don't guess it**, ask
  the user to paste the exact body, or refer them to Capella's UI's "View
  as JSON" feature.
- `capella_delete_cluster(org_id, project_id, cluster_id)` — **destructive**.
  Always restate the cluster name and project before calling.
- `capella_create_backup(org_id, project_id, cluster_id)` — triggers an
  immediate backup. Cheap; safe to retry on failure.
- `capella_restore_backup(org_id, project_id, cluster_id, backup_id, target_cluster_id=None)` —
  restore in place (omit `target_cluster_id`) or into a different cluster
  (set `target_cluster_id`). Always confirm the source backup id and
  destination cluster.

## What the v4 Management API covers for Analytics

The `capella_*` tools here wrap **operational-cluster** endpoints. Capella's v4
Management API also exposes a *separate* set of resource groups for **Capella
Analytics clusters**, which these tools do not cover. As of the current API
reference (major version 4) those groups are, verbatim:

- Columnar Analytics Clusters
- Columnar Analytics Cloud Snapshot Backups & Restore
- Columnar Analytics Cloud Snapshot Backups Schedule
- Columnar Analytics On/Off Schedule
- Columnar Analytics Private Endpoint Service
- Allowed CIDRs (Analytics Cluster)

plus the shared Organizations, Projects, Users and Api Keys groups. GCP support
for Analytics clusters and the private endpoint operations landed in March
2025; the snapshot backup and backup-schedule operations in November 2024.

Two things to tell users plainly:

1. The **API resource names still say "Columnar"** even though the product was
   renamed to **Capella Analytics** in August 2025. That is an API-surface
   lag, not a second product. Do not "correct" an endpoint name in a script.
2. An Analytics cluster is **not** an operational cluster. `capella_get_cluster`
   and friends will not find one. If the user needs Analytics-cluster
   lifecycle, point them at the Analytics endpoints above rather than guessing
   a payload.

Sources:
`https://docs.couchbase.com/analytics/management-api-reference/index.html`,
`https://docs.couchbase.com/analytics/management-api-guide/management-api-log.html`

## What the tools won't do

- They don't create projects or organizations (rarely needed; do that in
  the Capella UI), even though the v4 API itself has Organizations and
  Projects resource groups.
- They don't manage Capella Analytics clusters (see the section above).
- They don't manage cluster networking, allowed CIDRs, or VPC peering — use
  the Capella UI or the broader v4 API directly.
- They don't subscribe / unsubscribe billing.

## Common failure modes

- **`AnalyticsAuthError`**: the API key is missing the required role for the
  org. The fix is in the Capella UI, not here.
- **`AnalyticsNotFoundError`**: a stale org/project/cluster id. Re-list
  parents to refresh.
- **`AnalyticsRequestError` with status 400**: the `cluster_spec` doesn't
  match what Capella expects. Surface the message body to the user
  verbatim; it usually names the offending field.

## What to avoid

- Don't `capella_delete_cluster` without an explicit, named confirmation in
  the conversation.
- Don't poll cluster status aggressively during long-running provisions;
  Capella throttles its own API independently of this server. Back off on a
  429 and honour whatever the response says — don't hard-code a fixed interval
  as if it were a published limit.
- Don't store the Capella API key in plain config files. Use the env var.

## Rate limits & safety

Capella tools split across rate-limit categories:

- **`read`** (60/sec): `capella_list_organizations`, `capella_list_clusters`,
  `capella_get_cluster`, `capella_list_backups`, `capella_list_api_keys`.
- **`write`** (1/sec): `capella_create_cluster`, `capella_delete_cluster`,
  `capella_create_backup`, `capella_restore_backup`.

Capella's own API throttles separately from this server's limit, and the
exact Capella-side thresholds are not published in the docs — treat a 429
from Capella as authoritative rather than assuming a number. So two
independent limits apply: this server's (per-API-key, in-process) and
Capella's (their service).

If a `RateLimitExceeded` comes back from our server, honour
`retry_after_sec`. If a 429/throttle comes from Capella itself, surface
the message verbatim — it usually names the offending limit.

Don't try to work around the write-rate limit on `capella_delete_cluster`
or `capella_restore_backup` by raising `RATE_LIMIT_WRITE_PER_SEC`. The
limit is there precisely because these operations are destructive at
cloud scale.

## Related skills

- `cb-analytics-cluster` — once connected to a Capella cluster, cluster-level ops use these tools
- `couchbase-admin-mcp` — Capella control-plane administration through the Couchbase Admin MCP server: projects, clusters, credentials, allowed CIDRs and App Services (separate server, separate credentials)
- `couchbase-mcp` — the data-plane Couchbase MCP server, for documents, SQL++ and query diagnostics; it has no Capella control-plane tools
- `cb-analytics-security` — Analytics roles and service accounts, once a cluster exists
