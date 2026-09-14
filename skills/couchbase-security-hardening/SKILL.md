---
name: couchbase-security-hardening
description: "Harden and audit the security posture of a Couchbase Server deployment. Use whenever the user asks about TLS configuration, minimum TLS version, cipher suites, mTLS, certificate management, cluster encryption level, node-to-node encryption, LDAP or Active Directory integration, SAML SSO, PAM authentication, audit logging and audit event IDs, SIEM shipping, network isolation and firewall rules for Couchbase, RBAC design, scoped and collection-level roles, least privilege, password policy, locking and unlocking users, encryption at rest, KMIP or AWS KMS key management, compliance alignment (SOC 2, HIPAA, PCI DSS, FedRAMP), or 'how do I secure Couchbase for production'. Covers both Couchbase Server 7.x and 8.0, and notes which controls are Enterprise Edition only. Distinct from couchbase-app-integration, which covers TLS in SDK client code. Use proactively for new production deployments, compliance reviews and pre-certification hardening."
license: Apache-2.0
---

# Couchbase Security Hardening

Hardening a Couchbase Server deployment: TLS, RBAC, audit logging, encryption at rest, external authentication, network isolation, and compliance alignment.

Distinct from `couchbase-app-integration`, which covers TLS and certificate configuration inside application SDK clients.

## Two rules that prevent most wrong answers

**Gate every claim on version and edition.** 7.x and 8.0 are both in production, and several controls here — Native Encryption at Rest, user lock/unlock, node-to-node mTLS — arrived in 8.0. Several others are Enterprise Edition only and simply do not exist in Community Edition. Before answering "yes, Couchbase can do that," establish which release and which edition.

**Check role and event names against the reference for that release.** Role inventories and audit event IDs change between releases. Never write a role name or an audit event ID into automation from memory.

## When this skill applies

- "How do I secure Couchbase for production?"
- "How do I enable TLS and stop plaintext connections?"
- "How do I integrate Couchbase with LDAP / Active Directory / SAML?"
- "How do I design least-privilege RBAC? Can I scope a role to one collection?"
- "What audit events should I be capturing, and how do I get them into the SIEM?"
- "How do I enable encryption at rest? Do I need KMIP?"
- "How do I harden Couchbase for SOC 2 / HIPAA / PCI DSS?"
- "How do I configure password policy? Can I lock an account?"

## Pick the right reference

| Question | Read |
|---|---|
| TLS versions, cipher suites, cluster encryption level, certificates, mTLS | `references/tls.md` |
| Role design, scoped and collection-level roles, groups, password policy, user lock/unlock | `references/rbac.md` |
| LDAP, Active Directory, SAML, PAM, external users | `references/external-auth.md` |
| Audit configuration, filterable vs non-filterable events, event IDs, SIEM shipping | `references/audit-logging.md` |
| Native Encryption at Rest, KMIP and AWS KMS, key rotation, backup encryption | `references/encryption-at-rest.md` |
| Ports, firewall and security-group design, Capella network isolation | `references/network-hardening.md` |

## Production hardening checklist

**Authentication and access**
- [ ] The built-in administrator password is not the one from the install runbook
- [ ] Every application connects as a dedicated service account, never as the administrator
- [ ] Service accounts hold only the roles they need, scoped to a collection or scope where the role supports scoping
- [ ] Roles are granted through groups, not user by user
- [ ] Password policy sets a minimum length and character classes. Couchbase Server has **no** password-expiry setting — expiry for human accounts comes from the IdP
- [ ] Human logins go through LDAP or SAML where the organisation has an IdP, so MFA is enforced there
- [ ] There is a documented way to lock a compromised account. Couchbase Server has **no** automatic failed-attempt lockout; on 8.0+ an administrator can lock an account, and repeated `login failure` events (ID 8193) are the SIEM signal to act on

**Network and encryption**
- [ ] Minimum TLS version set to `tlsv1.2` or higher. TLS 1.0 and 1.1 are not supported on 7.6+
- [ ] Node-to-node encryption enabled, and the cluster encryption level raised to `strict` once every client is on TLS
- [ ] All SDK connections use `couchbases://`
- [ ] Only the TLS service ports are reachable from the application tier; node-to-node ports are confined to the cluster's private network
- [ ] Web Console over plaintext HTTP disabled, and the Console restricted to operator networks
- [ ] Node certificate expiry is monitored, and a rotation procedure has been rehearsed
- [ ] Capella: allowed IP list is specific; `0.0.0.0/0` appears nowhere

**Data protection**
- [ ] Encryption at rest satisfied — natively on 8.0+ Enterprise Edition, or at the storage layer otherwise, with the log and index paths covered too
- [ ] External key management (KMIP or AWS KMS) configured where key custody must be separated from data custody
- [ ] Backup archives encrypted, with the passphrase in a secrets manager and recoverable by more than one person

**Audit and visibility**
- [ ] Audit logging enabled. Note that administrative and authentication events are non-filterable and are on as soon as auditing is
- [ ] The filterable data-access events the compliance framework requires are confirmed **not** disabled
- [ ] Rotation configured, and `--prune-age` set only after off-node shipping is verified working
- [ ] Audit logs shipped from every node to the SIEM, tagged with cluster and node, with rules keyed on numeric event IDs

## Configuration surface

There is no security-specific MCP tooling to reach for. The official Couchbase MCP server (`couchbase/mcp-server-couchbase`, docs at https://mcp-server.couchbase.com/) is a data and query tool — schema discovery, key-value access, SQL++, query performance analysis — and it runs **read-only by default** (`CB_MCP_READ_ONLY_MODE=true`). It exposes no cluster-administration or security tools, so every control in this skill is applied through the Web Console, `couchbase-cli`, or the management REST API.

| Task | Surface |
|---|---|
| TLS version, cipher suites, encryption level, Console over HTTP, HSTS | `couchbase-cli setting-security` / `/settings/security` |
| Password policy | `couchbase-cli setting-password-policy` / `/settings/passwordPolicy` |
| Users, groups, roles, lock/unlock, temporary password | `couchbase-cli user-manage` |
| Audit configuration and filterable-event list | `couchbase-cli setting-audit` / `/settings/audit` |
| LDAP configuration | `couchbase-cli setting-ldap` |
| SAML configuration | Web Console, **Security → SAML** (7.6+, Enterprise Edition) |
| Encryption at rest keys and targets | `/settings/encryptionKeys`, `/settings/security/encryptionAtRest`, Web Console (8.0+, Enterprise Edition) |
| Certificates and trusted CAs | Web Console, **Security → Certificates**, plus the certificate REST endpoints |

Read any setting back with the `--get` (or `--get-settings`) form of the same command before changing it, and capture that output as the pre-change record.

## Related skills

- `couchbase-app-integration` — TLS and client-certificate configuration in SDK clients
- `couchbase-observability` — shipping operational logs and metrics; the metrics scrape account belongs to `external_stats_reader`
- `couchbase-kubernetes` — the same TLS and RBAC controls expressed as operator custom resources
- `couchbase-backup-restore` — backup encryption
- `couchbase-admin-mcp` — applying these TLS, RBAC, audit and encryption settings through the admin MCP server
- `couchbase-capella` — the same posture on Capella, where networking and credentials work differently
- `couchbase-coding-standards` — app-side secrets handling and injection hygiene, which cluster hardening does not cover
- `couchbase-mcp` — the MCP server's own security surface (read-only mode, credentials) when operating a hardened cluster
- `couchbase-mobile` — Sync Gateway and App Services authentication, a separate edge to harden
