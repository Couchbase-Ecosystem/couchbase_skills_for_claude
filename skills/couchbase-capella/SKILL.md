---
name: couchbase-capella
description: "Provision, configure, and manage Couchbase Capella deployments. Use whenever the user asks about Capella cluster setup, the Capella free tier, creating a Capella cluster, cluster options and Service Groups, cluster access credentials, Capella allowed IPs and CIDRs, Capella VPC peering, AWS PrivateLink, Azure Private Link, GCP Private Service Connect, Capella App Services setup, Capella networking, cluster access credentials vs organization roles, Capella organizations and projects, Capella connection strings, the Capella Management API v4, or 'how do I get started with Capella / set up Capella for production.' Distinct from couchbase-sizing (which covers capacity math) and couchbase-security-hardening (which covers TLS and RBAC). This skill covers Capella as a product — provisioning, networking, credentials, and connecting your application to it."
license: Apache-2.0
---

# Couchbase Capella

A skill for *provisioning and configuring* Couchbase Capella deployments — from the free tier through production, covering networking, credentials, and application connectivity.

This skill carries no pricing or cost information. Plan *names* and technical characteristics appear here; for costs, send the user to Couchbase directly.

Distinct from:
- `couchbase-sizing` — capacity and node sizing math
- `couchbase-security-hardening` — TLS, RBAC, and audit configuration once the cluster is running
- `couchbase-backup-restore` — Capella backup and restore

## When this skill applies

- "How do I create a Capella cluster?"
- "How do I connect my app to Capella?"
- "What's the difference between cluster access credentials and my Capella login?"
- "How do I set up allowed IPs / private networking?"
- "How do I set up VPC peering or a private endpoint with Capella?"
- "What are Capella orgs, projects, and clusters?"
- "How do I set up Capella App Services?"
- "What does the free tier give me?"

## Pick the right reference

| Question | Read |
|---|---|
| "Getting started — free tier, org/project structure, cluster options, first cluster" | `references/getting-started.md` |
| "Networking — allowed IPs, VPC peering, private endpoints" | `references/networking.md` |
| "Credentials — cluster access credentials, API keys, connection strings" | `references/credentials.md` |

## Key Capella concepts

**Organization → Project → Cluster** is the hierarchy. Everything lives under an org. Projects group clusters by environment (dev, staging, prod). Clusters are the actual Couchbase deployments.

**Cluster access credentials ≠ your Capella login.** Your Capella account (email/SSO) authenticates you to the management plane and carries organization and project roles. Applications authenticate to the data plane with *cluster access credentials*, created per cluster under **Settings → Cluster Access**. Always use cluster access credentials for SDK connections. (The Management API still names these endpoints "Database Credentials" — same object, older name. Source: https://docs.couchbase.com/cloud/clusters/manage-database-users.html)

**Services are deployed through Service Groups.** A Service Group is a set of nodes that share one compute and storage configuration and run the same Services. Cluster options are **Free**, **Single Node**, **Multi-Node** (3/5/7-node templates), and **Custom** (up to 27 nodes across Service Groups). Source: https://docs.couchbase.com/cloud/clusters/databases.html

**Allowed IPs** are IP allowlists at the cluster level. Your application's outbound IP(s) must be on the list before connections are accepted. Entries can be permanent or temporary with an expiration. For production, prefer private networking (VPC peering or a private endpoint) over public-internet allowlisting. Source: https://docs.couchbase.com/cloud/clusters/allow-ip-address.html

**Management API v4.** Programmatic management uses the Capella Management API, base URL `https://cloudapi.cloud.couchbase.com`, paths under `/v4`. Verified current as of September 2026; the OpenAPI document still reports version `v4.0`. Sources: https://docs.couchbase.com/cloud/management-api-guide/management-api-intro.html and https://docs.couchbase.com/cloud/management-api-reference/index.html

## Related skills

- `couchbase-sizing` — choosing compute and storage for each Service Group
- `couchbase-backup-restore` — managing Capella backups
- `couchbase-mobile` — Capella App Services for mobile sync
- `couchbase-observability` — Capella monitoring integration
- `couchbase-security-hardening` — RBAC and TLS on Capella
- `couchbase-columnar` — Capella Analytics and Enterprise Analytics, the separate analytical services that link to this cluster
- `couchbase-mcp` — operating the data plane (documents, SQL++, diagnostics) once the cluster is provisioned
