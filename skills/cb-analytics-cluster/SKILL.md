---
name: cb-analytics-cluster
description: |
  Use this skill when the user wants to inspect or configure the Couchbase
  cluster itself — node membership, memory quotas, rebalance, auto-failover,
  system events, or just verifying that a cluster is reachable. Trigger when
  they mention "cluster info", "ping", "rebalance", "auto-failover",
  "system events", "nodes", "memory quota", or "who_am_i".
license: Apache-2.0
---

# Cluster operations

You have 9 cluster-level tools, mostly read-only.

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

## Reachability and identity

- `ping_cluster(cluster)` — fast yes/no liveness check. Use this first when
  troubleshooting any other tool failure.
- `get_cluster_info(cluster)` — UUID + implementation version. Cheap; safe
  to call often.
- `who_am_i(cluster)` — what the cluster sees the current MCP user as
  (roles, domain). Useful when an `AnalyticsAuthError` shows up.

## Capacity and health

- `get_cluster_details(cluster)` — nodes, memory quotas (`memoryQuota` for
  the Data service, `cbasMemoryQuota` for the Analytics service), `balanced`,
  `rebalanceStatus`. Read before any capacity decision. Quotas are per-node and
  are set cluster-wide; report the values the cluster returns rather than
  asserting a minimum or recommended size.
- `get_cluster_tasks(cluster)` — every in-flight task (rebalance, compaction,
  XDCR). Empty list is the happy path.
- `get_rebalance_progress(cluster)` — focused view: rebalance only.
  Returns `{"status": "none"}` when nothing's running.

## Auto-failover

- `get_auto_failover_settings(cluster)` — read current settings.
- `configure_auto_failover(enabled, timeout, max_count, cluster)`.

Documented parameter bounds (Couchbase Server):

| Setting | Default | Range | Notes |
|---|---|---|---|
| `enabled` | on | on/off | — |
| `timeout` | **120 seconds** | 5–3600 s (the UI floor is 5 s) | How long a node must be unresponsive before failover |
| `max_count` | **1** | 1 up to the number of nodes configured | Values above 1 are **Enterprise Edition only**; Community Edition is capped at 1 |

Failover also requires the surviving nodes to form a majority quorum.

**The Analytics caveat you must not skip.** Automatic failover monitors the
health of the **Data and Index services only**. A node running only Search,
Eventing, Query, **Analytics**, or Backup can have that service go unhealthy
and *will not* be auto-failed-over, as long as its cluster-manager heartbeats
are still being sent and processed. So "turn on auto-failover" is **not** a
remedy for a sick Analytics node — that still needs a manual failover or a
service restart (see `cb-analytics-admin`). Do not tell a user auto-failover
will protect their Analytics service.

Source:
`https://docs.couchbase.com/server/current/learn/clusters-and-availability/automatic-failover.html`

Treat any specific "recommended" tuple as the user's own sizing decision, not a
Couchbase recommendation — the defaults above are what the product ships.

## Rebalance

Analytics participates in cluster rebalance like any other service: adding or
removing an Analytics node requires a rebalance to redistribute its data, and
`get_cluster_tasks` / `get_rebalance_progress` report it. Note that the shape
of the rebalance differs between the in-cluster Analytics Service and the two
standalone products (Capella Analytics and Enterprise Analytics manage their
own node topology and are not rebalanced through these Couchbase Server
endpoints) — if the user is on one of those, these tools do not apply.

## System events

`get_system_events(since_time, cluster)` returns recent operational events
(`info` / `warning` / `error`). `since_time` is an ISO 8601 timestamp; omit
it for "everything the cluster will give us".

Use this for post-incident triage:

> User: "Why did the cluster fail over at 03:00?"
> 1. `get_system_events(since_time="2026-05-24T02:50:00Z")`
> 2. Look for `severity="warning"|"error"` entries around that timestamp.

## Confirmation patterns

- `configure_auto_failover` *changes durable cluster state*. Always confirm
  before calling. Restate the values you're about to set and which cluster.
- Never call any of these against the wrong cluster — `cluster` parameter
  is optional but if you have any doubt, pass it explicitly. Use
  `list_clusters` from the meta tools when in doubt.

## What to avoid

- Don't poll `get_cluster_tasks` faster than once a second during a long
  rebalance; the management endpoint is shared with the GUI.
- Don't disable auto-failover in production unless you have an immediate
  reason and a plan to re-enable. Note the original values in chat before
  you change them so they're easy to restore.

## Rate limits & safety

Cluster tools are almost all `read` (60/sec):
`ping_cluster`, `get_cluster_info`, `get_cluster_details`,
`get_cluster_tasks`, `get_rebalance_progress`,
`get_auto_failover_settings`, `get_system_events`, `who_am_i`.

The single `write` (1/sec) tool here is `configure_auto_failover` —
matches the safety advice above: never call this without explicit
confirmation, and the rate limit gives you exactly one shot per second
to fat-finger it.

When polling `get_rebalance_progress` during a long rebalance, the read
rate (60/sec) is plenty but the management endpoint is shared with the
GUI. Once every 2–5 seconds is the polite poll interval; faster won't
get you better data and stresses the management plane.

If `RateLimitExceeded` comes back, honour `retry_after_sec` — back off,
don't retry-storm.

## Related skills

- `cb-analytics-admin` — Analytics service-level health (ingestion status, active queries) rather than cluster-level
- `couchbase-admin-mcp` — full cluster administration (rebalance, node management, XDCR, Eventing) through the Couchbase Admin MCP server
- `couchbase-mcp` — the data-plane Couchbase MCP server, for documents, SQL++ and query diagnostics
- `cb-analytics-capella` — provisioning, backups and API keys for a Capella cluster through the Cloud Management API
- `cb-analytics-mcp-setup` — installing and configuring the MCP server that exposes these cluster tools
- `cb-analytics-security` — creating and auditing the users and roles behind the identity `who_am_i` reports
