---
name: couchbase-admin-mcp
description: >-
  Administer Couchbase Server clusters and the Capella control plane through the
  Couchbase Admin MCP server. Use when the user asks to create or resize a bucket,
  manage scopes and collections, add or remove nodes, rebalance, fail over, recover,
  configure auto-failover or auto-compaction, manage users, groups, roles, audit
  settings or password policy, configure encryption at rest or KMIP, set up XDCR
  references and replications, manage Search Service indexes, deploy or pause
  Eventing functions, run or restore a backup, read cluster statistics, collect
  logs, or drive Capella projects, clusters, App Services and App Endpoints. Use
  proactively whenever an operation would change cluster state, so the read-only
  and confirmation gates are respected. Distinct from couchbase-mcp, which is the
  read-oriented data-plane server for documents, SQL++ and query diagnostics.
license: Apache-2.0
---

# Couchbase Admin MCP Server

The Couchbase Admin MCP server is a separate server from the data-plane Couchbase MCP
server. It exposes cluster administration and the Capella Management API v4 control
plane. The two servers do not share a tool namespace and are configured independently
— running both at once is normal and is usually what you want.

Repository: `Couchbase-Ecosystem/couchbase_admin_mcp_server` (Apache-2.0).

This skill covers what the server can do, how its safety model works, and how to
operate it without causing an outage. It deliberately does not reproduce the full tool
list: the inventory moves with each release, and the server can report its own.

## When this skill applies

- "Create a bucket / resize a bucket / change the storage backend"
- "Add a node, remove a node, rebalance, fail over, recover a node"
- "Set up auto-failover / auto-compaction / server groups / alerts"
- "Create a user, assign roles, configure LDAP or SAML, turn on auditing"
- "Turn on encryption at rest / configure KMIP"
- "Set up XDCR to another cluster" / "pause a replication"
- "Create a Search index / pause ingest"
- "Deploy, pause or undeploy an Eventing function"
- "Run a backup / restore from a backup repository"
- "Show me cluster stats / collect logs for support"
- "Create a Capella project or cluster / manage App Services / manage App Endpoints"

If the request is to read documents, write SQL++, explain a query, or diagnose query
performance, that is `couchbase-mcp`, not this skill.

## Step 0 — Confirm the connection and the posture (pre-flight)

Before proposing any operation, establish three things:

1. **Is the server reachable, and in which profile?** Call `cb_mcp_status`. The server
   refuses to start at all unless `CB_ADMIN_PROFILE` is set to `workstation` or
   `enterprise`; there is no default. The profile determines how much the deployment
   is allowed to relax.
2. **Is it read-only?** `CB_ADMIN_READ_ONLY_MODE` defaults to `true`, and in that mode
   the write tools are not merely refused — they are not loaded. If a write tool is
   absent, the server is read-only; say so rather than reporting the tool as missing.
3. **What is actually available here?** `cb_mcp_list_tools` enumerates the loaded
   tools and `cb_mcp_get_tool_info` describes one. Treat these as the authoritative
   inventory for the connected server, ahead of any list written down anywhere.

Never infer the posture from a failed call. Ask the server.

## Pick the right reference

| Question | Read |
|---|---|
| "What are the trust layers, and how do I get past a confirmation gate safely?" | `references/safety-and-trust.md` |
| "How do I configure, deploy or containerize this server?" | `references/configuration.md` |
| "What can it actually do — which families, which are destructive?" | `references/tool-families.md` |
| "How do I run a real change end to end without breaking the cluster?" | `references/operational-runbooks.md` |

## Core principles

**Read-only is the resting state.** The server ships read-only and every tool carries a
`readOnlyHint` / `destructiveHint` annotation. Enabling writes is a deliberate act by
whoever deployed the server, not something an agent negotiates mid-session. If a write
is needed and the server is read-only, say what would need to change and stop.

**Preview before you change anything.** Every write tool accepts `dry_run: true`, and
the server can force it globally with `CB_ADMIN_DRY_RUN=true`. The environment variable
wins: `dry_run: false` cannot escape a server-wide preview. Run the dry run, show the
user what it reports, and only then propose the real call. A dry run is a validation of
the request, not a guarantee the cluster will accept it.

**Destructive means destructive.** Bucket delete and flush, node removal, hard and
graceful failover, rebalance, user deletion, replication deletion, encryption and KMIP
changes, audit and password-policy changes, and the Capella teardown operations all
change state in ways that are slow or impossible to undo. Treat every one as requiring
explicit, specific human approval — naming the cluster and the object — even when the
server would allow it.

**One change at a time, and let it finish.** Topology operations serialize. Do not
start a rebalance while a failover is recovering, and do not batch unrelated cluster
changes into one turn because they were all requested at once.

**Capella and self-managed are different control planes.** The `capella_*` tools drive
the Capella Management API v4 and need Capella API credentials, not cluster
credentials. The `admin_*` tools drive a cluster's own management REST API. A request
about "the cluster" has to be resolved to one of the two before you pick a tool.

## Tool families

The server is organized into families. Counts move between releases — use
`cb_mcp_list_tools` for the live figure.

| Family | Covers | Risk profile |
|---|---|---|
| Server status | Server posture, tool introspection | read only |
| Buckets | Create, update, delete, flush, compact, sample buckets | read + write + destructive |
| Scopes and collections | Create and drop scopes and collections | read + write + destructive |
| Cluster | Nodes, rebalance, failover, recovery, auto-failover, server groups, auto-compaction, alerts, log collection | read + write + destructive |
| Security | Users, groups, roles, audit, password policy, security settings | read + write + destructive |
| Encryption | Encryption at rest, KMIP | read + destructive |
| Indexes | GSI create, drop, build, index settings | read + write + destructive |
| Search | Search Service index lifecycle, stats, ingest control | read + write + destructive |
| Eventing | Function lifecycle, deploy, pause, resume, stats | read + write + destructive |
| XDCR | Remote references, replications, settings | read + write + destructive |
| Backup | Repositories, backup runs, restore | read + write + destructive |
| Statistics | Bucket, node, index and query stats, system events, Prometheus targets | read + destructive (internal settings) |
| Diagnostics | Schema inference, EXPLAIN, Index Advisor, query performance analysis | read only |
| 8.x features | Vector index creation, user lock/unlock, temporary users, XDCR conflict log | read + write + destructive |
| Capella | Organizations, projects, clusters, buckets, scopes, collections, credentials, allowed CIDRs, App Services, App Endpoints, events, certificates | read + write + destructive |

`references/tool-families.md` breaks each family down and names the operations that
carry the highest blast radius.

## Version gating

The `8.x features` family exists because those operations have no pre-8.0 equivalent:
vector index creation, administrator-initiated user lock and unlock, temporary users,
and the XDCR conflict log. Against a 7.x cluster they will not work — confirm the
server version before proposing them.

## Scope

This skill does not cover: writing or tuning SQL++ (see `couchbase-sqlpp-tuning`),
document modeling (`couchbase-data-modeling`), the read-oriented data plane
(`couchbase-mcp`), or the Analytics service (`cb-analytics-*`). For the reasoning
behind a change — whether to fail over, how to size a bucket, which index to build —
use the subject skill and bring the decision here for execution.

## Related skills

- `couchbase-mcp` — the data-plane MCP server: documents, SQL++, query diagnostics
- `couchbase-fts` — Search index design and query syntax, behind this server's `admin_fts_*` lifecycle tools
- `couchbase-ai-applications` — vector index selection, behind this server's `admin_vector_index_*` tools
- `couchbase-performance-tuning` — what to change and why, before using `admin_cluster_memory_set` here
- `couchbase-upgrade` — the upgrade sequence this server's cluster and XDCR tools verify
- `couchbase-security-hardening` — what a hardened cluster should look like, before you configure it here
- `couchbase-backup-restore` — backup strategy and `cbbackupmgr`, which this server's backup family executes against
- `couchbase-xdcr` — topology and conflict-resolution design, ahead of creating a replication
- `couchbase-kubernetes` — on Kubernetes the Autonomous Operator owns most of this surface instead
- `cb-analytics-capella` — the Analytics side of Capella, which this server's `capella_*` tools do not cover
- `cb-analytics-cluster` — cluster-level operations as seen from the Analytics service

## References

- [`references/safety-and-trust.md`](references/safety-and-trust.md) — the trust layers, dry run, confirmation and the hard ceiling
- [`references/configuration.md`](references/configuration.md) — environment variables, profiles, transports, Docker, logging
- [`references/tool-families.md`](references/tool-families.md) — family-by-family breakdown with risk tiers
- [`references/operational-runbooks.md`](references/operational-runbooks.md) — end-to-end procedures for the common changes
