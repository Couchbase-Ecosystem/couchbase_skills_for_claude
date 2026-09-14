---
name: cb-analytics-security
description: |
  Use this skill when the user wants to manage Couchbase users, groups,
  roles, or check permissions on the cluster — creating service accounts,
  rotating passwords, granting analytics privileges, or auditing who can do
  what. Trigger when they mention "user", "group", "role", "RBAC",
  "permission", "upsert_user", "check_permissions", "local domain",
  "external domain", or "analytics_reader", "analytics_select", "analytics_manager", or "analytics_admin".
license: Apache-2.0
---

# Couchbase RBAC via cb-analytics-mcp

You have 9 RBAC tools: list/get/upsert/delete user, list/upsert/delete group,
list roles, and check permissions.

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

## The two domains

Couchbase users live in one of two domains:

- **local** — created and managed inside Couchbase itself.
- **external** — authenticated via LDAP / SAML / PAM, mirrored locally with
  role bindings.

Every user-related tool takes a `domain` argument. If you list users without
a domain you get both.

## Role-spec format

`roles` is a single comma-separated string, never a list. **Whether a role
takes parameters is fixed per role — you cannot add `[*]` to an unparameterised
role.** The four Analytics roles on a Couchbase Server / Capella operational
cluster are:

| Role id | Parameters | What it grants |
|---|---|---|
| `analytics_reader` | **none** | Query all Analytics datasets |
| `analytics_select` | `[bucket:scope:collection]` | SELECT on the Analytics collections mapped from that bucket/scope/collection |
| `analytics_manager` | `[bucket]` | Manage Analytics collections/links for that bucket |
| `analytics_admin` | **none** | Full Analytics Service administration |

```
analytics_reader                              # correct — no parameter
analytics_select[bucket1]                     # bucket level
analytics_select[bucket1:scope1]              # scope level
analytics_select[bucket1:scope1:coll1]        # collection level
analytics_manager[bucket1]
analytics_admin,query_select[bucket1]         # multiple roles
```

`analytics_reader[*]` and `analytics_admin[*]` are **not valid** — those two
roles take no parameters. Source:
`https://docs.couchbase.com/server/current/cli/cbcli/couchbase-cli-user-manage.html`

Use `list_roles()` first if you don't know what's available — it returns
every role the cluster supports, with descriptions. Role sets differ between
Couchbase Server minor versions, so prefer `list_roles()` over this table when
the two disagree.

### The other two Analytics products have different roles

Do not carry these role names across:

- **Enterprise Analytics** uses its own set, including `analytics_access`
  (non-administrative) and an "Enterprise Analytics Admin" administrative role,
  alongside `ro_admin`, `cluster_admin`, `security_admin`,
  `user_admin_external`, `external_stats_reader`. Privileges apply at
  database/scope/collection level. Source:
  `https://docs.couchbase.com/enterprise-analytics/current/manage/manage-security/user-roles-privileges.html`
- **Capella Analytics** uses **access control accounts** (programmatic /
  application-level, not tied to a Capella UI user) with four preset roles that
  cannot be deleted: `sys_data_admin`, `sys_data_reader`,
  `sys_external_stats_reader`, `sys_view_reader`. Custom roles may not start
  with `sys_`. Privileges are grantable at instance, database, scope and
  collection level. Only an Organization Owner or Project Owner can create or
  modify them. Source:
  `https://docs.couchbase.com/analytics/admin/auth/auth-data.html`

## Creating a service account

For Claude itself, or any automation, create a least-privileged user:

```
upsert_user(
    domain="local",
    username="cb-mcp",
    roles="analytics_reader",
    password="<generated>",
    full_name="cb-analytics-mcp service account"
)
```

If the workflow only needs specific data, prefer scoped `analytics_select`
grants over the cluster-wide `analytics_reader`:

```
roles="analytics_select[travel-sample:inventory]"
```

**Never** use `analytics_admin` or `cluster_admin` for the MCP server's
cluster credentials in production. Grant only what the workflow needs.

## Password handling

The password is passed as a plain string into the tool and immediately
wrapped in `SecretStr` inside the impl, then unwrapped only at the HTTP
boundary. The audit log redacts it. That said:

- Generate strong passwords (`secrets.token_urlsafe(32)`).
- Rotate by calling `upsert_user` again with a new `password`.
- Never echo a password back to the user in chat.

## Checking permissions

`check_permissions(permissions="cluster.analytics!read,cluster.admin!write")`
returns a dict mapping each permission to `true`/`false` for the currently
authenticated user (the one in `CB_ANALYTICS_USERNAME`). Use this when:

- A tool returns `AnalyticsAuthError` and you want to confirm whether RBAC
  is the cause.
- You're auditing what the service account can actually do.

## Groups

Groups bundle role assignments and apply them to multiple users; a user is
granted the roles of every group they belong to. Workflow:

1. `upsert_group("analytics-readers", roles="analytics_reader", description="Read-only analytics users")`
2. Add the user to the group. **Group membership is a separate field from
   `roles` — it is not a role string.** In the underlying REST API it is the
   `groups` form parameter on
   `PUT /settings/rbac/users/local/<username>`; in `couchbase-cli user-manage`
   it is `--user-groups`. If `upsert_user` in this MCP server does not expose a
   groups argument, say so and point the user at the CLI or REST call rather
   than inventing a `roles="local:<group>"` syntax — that form is not
   documented.

Sources: `https://docs.couchbase.com/server/current/rest-api/rbac.html`,
`https://docs.couchbase.com/server/current/cli/cbcli/couchbase-cli-user-manage.html`

Group-based role assignment also exists in Enterprise Analytics, with
`groups` and `external_groups` on the user record.

## What to avoid

- Don't grant `cluster_admin` to "make things work" — find the specific role.
- Don't delete a user before deleting / reassigning what they own (libraries,
  active requests).
- Don't store passwords in the cluster config file. Use environment vars or
  a secrets manager instead.
- Don't echo a generated password back to the chat — show it once via a
  side channel (1Password, vault, etc.) and ask the user to confirm it's
  stored.

## Rate limits & safety

These limits are enforced **by this MCP server**, in-process, per API key.
Couchbase's own RBAC endpoints do not publish a comparable per-second limit —
do not describe these numbers to a user as a Couchbase product limit.

Security/RBAC tools split across two categories:

- **`read`** (60/sec): `list_users`, `get_user`, `list_groups`,
  `list_roles`, `check_permissions`.
- **`write`** (1/sec, intentionally tight): `upsert_user`, `delete_user`,
  `upsert_group`, `delete_group`.

The 1/sec write limit is deliberate — RBAC changes are durable cluster
state and the typical error mode is "did something irreversible
quickly". Bulk-provisioning users from a roster? Sequence them, accept
the ~1 second per user.

If `RateLimitExceeded` comes back on an `upsert_user` or `delete_user`,
honour `retry_after_sec`. Don't retry-storm.

Reads (`list_users`, `check_permissions`, etc.) share the global `read`
bucket. If you're auditing a permissions matrix, batch — one
`list_users` then targeted `check_permissions` calls is friendlier than
calling `get_user` per user-per-role combination.

Worth noting: rate limits are per **API key**, not per cluster. If a
single bearer token is doing both heavy RBAC bulk-load AND read-heavy
inspection at the same time, they contend for separate buckets, but the
bulk-load can starve other writes on the same key. Use distinct API
keys per workload if this matters.

## Related skills

- `cb-analytics-mcp-setup` — the MCP server's own credentials (`CB_ANALYTICS_USERNAME`, `MCP_API_KEY`) are configured here, not via RBAC tools
- `cb-analytics-cluster` — `who_am_i` to verify the effective role of the current MCP connection
- `cb-analytics-capella` — provisioning the cluster these roles are granted on
