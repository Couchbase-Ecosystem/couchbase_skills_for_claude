---
name: couchbase-eventing
description: "Design, deploy, and troubleshoot Couchbase Eventing functions. Use whenever the user asks about Eventing, eventing functions, JavaScript that runs on document mutations, listen-to location, Eventing storage or metadata keyspace, OnUpdate, OnDelete, OnDeploy, Eventing timers, curl() bindings, SQL++ inside functions, bucket and URL and constant bindings, feed boundary, deployment state (deployed / undeployed / paused), worker count, DCP deduplication, the Eventing Service, or 'how do I run code when a document changes.' Distinct from couchbase-app-integration (SDK-based change processing outside the cluster). Use proactively for change-driven processing needs: cache warming, audit logging, cross-collection sync, event publishing, and derived document generation."
license: Apache-2.0
---

# Couchbase Eventing

A skill for *designing and operating* Couchbase Eventing functions — JavaScript that runs in response to document mutations in a source collection.

Distinct from:
- `couchbase-app-integration` — SDK-based DCP consumer code for change processing outside the cluster
- `couchbase-data-modeling` — document shape decisions

## Edition gating — read this first

**The Eventing Service is Enterprise Edition.** So are Timers, `curl()`, and function export/import. Do not design an Eventing solution for a Community Edition deployment; point at an SDK-based DCP consumer instead (`couchbase-app-integration`).

## When this skill applies

- "How do Eventing functions work?" / "How do I deploy one?"
- "How do I write an OnUpdate or OnDelete handler?"
- "How do I call an external API from Eventing?"
- "Can I run SQL++ from inside an Eventing function?"
- "How do I sync data between two collections automatically?"
- "Eventing function is deployed but nothing happens"
- "What's the Eventing storage / metadata keyspace for?"
- "What changed in Eventing in 8.0?"

## Pick the right reference

| Question | Read |
|---|---|
| "How do I write the JavaScript? OnUpdate, OnDelete, OnDeploy, timers, curl, SQL++, what's unsupported?" | `references/function-authoring.md` |
| "How do I configure and deploy — function scope, listen-to location, storage keyspace, bindings, workers, feed boundary?" | `references/deployment.md` |
| "Function isn't triggering / processing slowly / throwing errors" | `references/troubleshooting.md` |

## Terminology — use the current names

The UI and documentation use these terms; older material uses the ones in brackets, which you should translate rather than repeat.

| Current term | Older term |
|---|---|
| Listen To Location (source keyspace) | source bucket |
| Eventing Storage (metadata keyspace) | metadata bucket |
| Function Scope (a `bucket.scope` RBAC grouping) | — |
| Bucket alias / URL alias / Constant alias bindings | bucket binding / curl binding |
| Feed Boundary: Everything, From now | `from_now` flag |

## Three core principles

**Principle 1 — Handlers must be idempotent.**
Eventing consumes Couchbase's internal DCP feed. In steady state each mutation triggers `OnUpdate` or `OnDelete` once, but during node failures, rebalances, and redeploys a mutation can be delivered more than once. Running the same handler against the same document twice must produce the same result.

**Principle 2 — The Eventing Storage keyspace belongs to the service.**
It holds DCP checkpoints, timer state, and internal function documents. Your function's JavaScript must never write to or delete from it. Use a dedicated collection that no application touches. A common Eventing Storage collection *can* be shared across the functions of one tenant, but never share it with application data, and never make it the Listen To Location of another function.

**Principle 3 — Eventing is not a general compute layer.**
Handlers run per-mutation on Eventing nodes with no asynchrony and no global state. Heavy computation, slow `curl()` calls, or expensive SQL++ inside a handler queues mutations and grows the DCP backlog. For anything substantial, emit a lightweight work-order document and process it elsewhere.

## Deployment lifecycle

```
Undeployed ──deploy──► Deployed ──undeploy──► Undeployed
                           │
                         pause
                           │
                           ▼
                        Paused ──resume──► Deployed
```

- **Undeployed** — the definition exists; nothing is processed and no DCP checkpoint is held.
- **Deployed** — actively processing; checkpoint maintained.
- **Paused** — processing stops, checkpoint position is held. Resume continues from where it stopped.
- Pause is only available from Deployed. **Edit JavaScript** is only available when Paused or Undeployed; while Deployed you can only view it.
- Use **pause → edit → resume** to change function code without reprocessing history. Undeploying discards the checkpoint.
- **8.0:** `OnDeploy` runs once on deploy *and* on resume, before any mutations are processed.

**Feed Boundary** decides whether an initial deployment covers existing documents:

- **Everything** — process all mutations available in the cluster from the Listen To Location.
- **From now** — process only mutations occurring after deployment.

It is a **persistent setting in the function definition** and can only be set or changed when the function is created, undeployed, or paused. It is not a parameter of the deploy call. In the REST/exported form the setting is `dcp_stream_boundary`, with values `everything` and `from_now`.

## What changed in 8.0

- **`OnDeploy` handler** — runs once on deploy or resume, before mutations, with the same JavaScript capabilities as `OnUpdate`/`OnDelete`. Use it for one-time setup such as registering a timer. Keep it short: it has its own **OnDeploy Timeout** (default 60 s) and a failure leaves the function in its previous state with no mutations processed.
- **Scope-level configuration** — options such as `enable_curl` and `enable_debugger` can now be set at bucket or scope level.
- **`num_nodes_running`** — restrict a function to a set number of Eventing nodes instead of all of them. Set at function scope config level; if fewer nodes are available, it runs on all of them.
- **Per-request `curl` timeout** — a timeout can be specified in seconds on an individual `curl()` call, taking precedence over the script timeout.

Source: [What's New in 8.0](https://docs.couchbase.com/server/current/introduction/whats-new.html)

## Operating Eventing

Manage functions from the Eventing page in Couchbase Web Console, `couchbase-cli`, or the Eventing REST API (per-node, on port 8096 for statistics). Functions can be exported and imported as JSON to move them between environments — do not hand-edit an exported file before reimporting it.

The official Couchbase MCP server (`couchbase/mcp-server-couchbase`, https://mcp-server.couchbase.com/) is a data-plane server, **read-only by default** (`CB_MCP_READ_ONLY_MODE`), and does not manage Eventing functions. Use it to inspect source and destination documents while debugging a handler; use the UI, CLI, or REST API to deploy.

RBAC: **Full Admin** or **Eventing Full Admin** can manage all Eventing functions and can set Function Scope to `*.*`. Other users must use a Function Scope referencing a real `bucket.scope` they have rights on.

## Related skills

- `couchbase-app-integration` — SDK-based DCP consumers, the alternative when Eventing's per-mutation model or Enterprise Edition requirement does not fit
- `couchbase-data-modeling` — source and derived document shapes
- `couchbase-xdcr` — Eventing functions writing into XDCR-replicated buckets can create replication loops in bidirectional topologies
- `couchbase-observability` — function statistics, backlog metrics and alert thresholds for deployed functions
