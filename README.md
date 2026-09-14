# Couchbase Skills for Claude

Agent skills that bring Couchbase expertise to coding agents — covering every major service and deployment pattern, from application integration and data modeling through SQL++ tuning, Search and vector, AI applications, XDCR, Eventing, mobile and App Services, Kubernetes, security hardening, and Analytics.

**31 skills · 133 files · ~24,000 lines**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

> This project is **community-maintained**, which means it is **not officially supported** by the Couchbase support team. Our support portal is unable to assist with requests related to this project, so we kindly ask that all inquiries stay within GitHub.

---

## What agent skills are

A skill is a `SKILL.md` playbook plus optional `references/*.md` deep dives. The agent loads a skill's name and description at startup, pulls the body in when the skill triggers, and reads a reference file only when the body routes it there. That progressive disclosure is what lets a 24,000-line corpus sit behind a few hundred tokens of always-on context.

These skills follow the open [Agent Skills specification](https://agentskills.io/specification), so they work in Claude Code, the Claude apps, Codex, Cursor, Gemini CLI, GitHub Copilot CLI, and anything else that implements the standard.

They are **MCP-grounded**: they expect a live cluster behind the [Couchbase MCP server](https://github.com/couchbase/mcp-server-couchbase) and prefer real evidence — schema, indexes, `EXPLAIN` output, live statistics — over generic advice. They also treat the cluster as **read-only** until a human explicitly approves a write or DDL.

---

## Install

This repository is itself the plugin and the marketplace source.

| Harness | Install |
|---|---|
| **Claude Code** | `/plugin marketplace add Couchbase-Ecosystem/couchbase_skills_for_claude`, then `/plugin install couchbase-skills@couchbase-skills` |
| **Claude Desktop** | **Customize** → `+` next to **Personal Plugins** → **Add** → **Add Marketplace** → enter `Couchbase-Ecosystem/couchbase_skills_for_claude` → **Sync**, then `+` to install **couchbase-skills** |
| **Codex CLI** | `codex plugin marketplace add Couchbase-Ecosystem/couchbase_skills_for_claude`, then `/plugins` in a session to install |
| **Gemini CLI** | `gemini extensions install https://github.com/Couchbase-Ecosystem/couchbase_skills_for_claude` |
| **GitHub Copilot CLI** | `/plugin marketplace add Couchbase-Ecosystem/couchbase_skills_for_claude`, then `/plugin install couchbase-skills@couchbase-skills` |
| **Cursor** | Add `Couchbase-Ecosystem/couchbase_skills_for_claude` as a plugin marketplace, then install `couchbase-skills` |

After installing, connect to your cluster by setting `CB_CONNECTION_STRING`, `CB_USERNAME` and `CB_PASSWORD`. The bundled MCP server configuration (`mcp.json`) runs read-only by default; see [`skills/couchbase-mcp/`](skills/couchbase-mcp/) for the full configuration surface.

### Without a plugin host

Copy the skill directories you want into your project's `.claude/skills/`, or paste a `SKILL.md` into a Claude Project's knowledge. Each skill is self-contained; the `references/` files load on demand only when the agent is told to read them.

---

## Skills

| Skill | What it covers | References |
|---|---|---|
| [`couchbase-mcp`](skills/couchbase-mcp/) | Operates a Couchbase cluster through the official Couchbase MCP server — documents, SQL++, schema, indexes, query diagnostics. | 7 |
| [`couchbase-admin-mcp`](skills/couchbase-admin-mcp/) | Administers clusters and the Capella control plane through the Couchbase Admin MCP server, with its read-only, dry-run and confirmation gates. | 4 |
| [`couchbase-sqlpp-tuning`](skills/couchbase-sqlpp-tuning/) | Diagnoses and tunes slow SQL++ queries — EXPLAIN plans, index design, the cost-based optimizer, array indexes, pagination. | 7 |
| [`couchbase-data-modeling`](skills/couchbase-data-modeling/) | Document models, boundaries, key design, embed vs reference, TTL, time-series, and migration from relational and document stores. | 7 |
| [`couchbase-app-integration`](skills/couchbase-app-integration/) | SDK integration — connection lifecycle, retry, durability, scan consistency, transactions, XDCR-aware patterns. | 7 |
| [`couchbase-coding-standards`](skills/couchbase-coding-standards/) | Coding standards for production Couchbase code: SDK idioms, key and field conventions, error and CAS handling, parameterized SQL++, review checklists. | 5 |
| [`couchbase-sizing`](skills/couchbase-sizing/) | Cluster sizing math — RAM, disk, node count, replicas, index memory, and Capella service-group selection. | 7 |
| [`couchbase-migration-execution`](skills/couchbase-migration-execution/) | Data migration — `cbmigrate`, dual-write, CDC, validation, cutover and rollback runbooks. | 7 |
| [`couchbase-fts`](skills/couchbase-fts/) | The Search Service and vector search — index design, analyzers, synonyms, query types, hybrid search. | 6 |
| [`couchbase-ai-applications`](skills/couchbase-ai-applications/) | AI application design — vector index selection, RAG pipelines, embedding strategy, agent memory, LLM framework integration. | 5 |
| [`couchbase-transactions`](skills/couchbase-transactions/) | Distributed ACID transactions — when to use them, mechanics, retry, and what is not supported inside one. | 3 |
| [`couchbase-eventing`](skills/couchbase-eventing/) | Eventing functions — handlers, timers, bindings, SQL++ in functions, deployment lifecycle. | 3 |
| [`couchbase-xdcr`](skills/couchbase-xdcr/) | Cross Data Center Replication — topology, conflict resolution, conflict logging, filtering, and the xattr constraints. | 4 |
| [`couchbase-backup-restore`](skills/couchbase-backup-restore/) | `cbbackupmgr`, the Backup Service, object-store archives, and what Capella managed backups do and do not restore. | 4 |
| [`couchbase-mobile`](skills/couchbase-mobile/) | Couchbase Lite, Sync Gateway, Edge Server and Capella App Services, including the 4.x upgrade and metadata-migration behaviour. | 4 |
| [`couchbase-capella`](skills/couchbase-capella/) | Capella provisioning, networking, credentials, allowed CIDRs and the Management API v4. | 3 |
| [`couchbase-kubernetes`](skills/couchbase-kubernetes/) | The Couchbase Autonomous Operator — CRDs, availability-zone awareness, rolling upgrades, persistent volumes. | 4 |
| [`couchbase-security-hardening`](skills/couchbase-security-hardening/) | TLS, RBAC design, LDAP and SAML, audit logging, encryption at rest and KMIP, network hardening. | 6 |
| [`couchbase-observability`](skills/couchbase-observability/) | Metrics that exist in current releases, scrape configuration and least-privilege, and how to derive alert thresholds. | 4 |
| [`couchbase-performance-tuning`](skills/couchbase-performance-tuning/) | Cluster performance — KV latency, DCP backpressure, compaction, connection limits, system tuning. | 3 |
| [`couchbase-upgrade`](skills/couchbase-upgrade/) | Supported upgrade paths, 8.0 breaking changes and removals, and the pre- and post-upgrade checklist. | — |
| [`couchbase-magma`](skills/couchbase-magma/) | The Magma storage engine — Couchstore comparison, vBucket counts, memory ratios, and backend migration. | — |
| [`couchbase-columnar`](skills/couchbase-columnar/) | Capella Analytics and Couchbase Enterprise Analytics — architecture, links to operational data, BI connectivity. | 2 |

### Analytics service skills

These eight skills document an Analytics MCP server and its operational surface. See [`FINDINGS.md`](FINDINGS.md) for their current homing status.

| Skill | What it covers |
|---|---|
| [`cb-analytics-query`](skills/cb-analytics-query/) | SQL++ for Analytics — tool selection, pagination, truncation, scan consistency |
| [`cb-analytics-schema`](skills/cb-analytics-schema/) | Scope and collection discovery, schema inference, data dictionary workflows |
| [`cb-analytics-admin`](skills/cb-analytics-admin/) | Runtime management — ingestion health, active requests, cancel, restart |
| [`cb-analytics-links`](skills/cb-analytics-links/) | External data-source links and which Analytics product supports which source |
| [`cb-analytics-security`](skills/cb-analytics-security/) | Analytics RBAC — users, groups, roles, service accounts |
| [`cb-analytics-cluster`](skills/cb-analytics-cluster/) | Cluster-level operations — nodes, quotas, rebalance, auto-failover, system events |
| [`cb-analytics-capella`](skills/cb-analytics-capella/) | Capella control-plane operations for Analytics |
| [`cb-analytics-mcp-setup`](skills/cb-analytics-mcp-setup/) | Installing and configuring the Analytics MCP server |

---

## Repository layout

```
skills/<skill-name>/SKILL.md          # the playbook — frontmatter, routing table, workflow
skills/<skill-name>/references/*.md   # deep dives, one level deep, linked from SKILL.md
skills/OWNERS.yaml                    # a reviewer and a review cadence for every skill

testing/README.md                     # eval schema and how to add a case
testing/<skill-name>/evals/evals.json # eval cases, including regression pins
tools/validate-skills.sh              # specification + house conventions gate
tools/run-evals.py                    # eval schema validation, grader self-test, execution
tools/validate-manifests.py           # packaging and cross-file consistency gate
tools/validate-links.py               # markdown link and anchor gate

.claude-plugin/ .codex-plugin/ .cursor-plugin/   # per-harness plugin manifests
mcp.json  gemini-extension.json                  # MCP server wiring
AGENTS.md  GEMINI.md                             # agent context files
BUILD.md                                         # the build and verification process
CONTRIBUTING.md                                  # how to change a skill
CODE_OF_CONDUCT.md  SECURITY.md                  # community and vulnerability-reporting policy
.github/workflows/                               # validate-skills (the gates) and evals (manual/scheduled)
FINDINGS.md                                      # open questions for Couchbase engineering
docs/skill-authoring-standard.md                 # the authoring standard these skills follow
```

---

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) for the workflow and [`BUILD.md`](BUILD.md) for the verification process every change has to pass. The short version: cite a docs.couchbase.com page for any version-sensitive claim, gate version-specific content instead of deleting the old guidance, keep the cluster read-only by default, and run the four validators before you open a pull request.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). To report a security issue, see [`SECURITY.md`](SECURITY.md) — please do not open a public issue.

---

## Related projects

| Project | What it is |
|---|---|
| [`couchbase/mcp-server-couchbase`](https://github.com/couchbase/mcp-server-couchbase) | The official Couchbase MCP server — the data plane these skills are grounded in |
| [`Couchbase-Ecosystem/couchbase_admin_mcp_server`](https://github.com/Couchbase-Ecosystem/couchbase_admin_mcp_server) | The Couchbase Admin MCP server — cluster and Capella administration |
| [`Couchbase-Ecosystem/agent-skills`](https://github.com/Couchbase-Ecosystem/agent-skills) | Couchbase agent skills and the plugin marketplace whose conventions this repository follows |

---

## License

Apache License 2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

Couchbase is a trademark of Couchbase, Inc.
