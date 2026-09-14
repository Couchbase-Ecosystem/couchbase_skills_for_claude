# RBAC design

## Contents

- [The Couchbase RBAC model](#the-couchbase-rbac-model)
- [Scoped (bucket / scope / collection) roles](#scoped-bucket--scope--collection-roles)
- [Roles for common use cases](#roles-for-common-use-cases)
- [Least-privilege design process](#least-privilege-design-process)
- [Group structure for teams](#group-structure-for-teams)
- [Password policy](#password-policy)
- [Locking and unlocking users](#locking-and-unlocking-users)
- [RBAC audit](#rbac-audit)

## The Couchbase RBAC model

Couchbase uses role-based access control with two assignment mechanisms:

- **Direct role assignment** — roles attached to a user.
- **Group membership** — the user belongs to a group; the group carries the roles.

Use groups for anything beyond a one-off service account. Groups make auditing and offboarding far easier, and they are the only sane way to hand roles to externally authenticated users.

Users live in one of two domains: `local` (credentials stored in Couchbase) and `external` (LDAP/SAML/PAM — authentication delegated, no password stored in Couchbase).

Always confirm role names against the roles reference for the release you are running before writing them into automation. Role inventory changes between releases.

## Scoped (bucket / scope / collection) roles

Some roles can be narrowed to a bucket, a scope, or a single collection. Others are cluster-wide and cannot be narrowed at all.

The parameter form is `role[bucket:scope:collection]`, with `*` meaning "all at this level":

```
data_reader[orders]                     # whole bucket
data_reader[orders:sales]               # one scope
data_reader[orders:sales:invoices]      # one collection
data_reader[*]                          # every bucket — avoid
```

Roles that accept scoping include the data roles (`data_reader`, `data_writer`, `data_dcp_reader`, `data_monitor`), the query roles (`query_select`, `query_insert`, `query_update`, `query_delete`, `query_manage_index`, the query function roles), the Search roles (`search_admin`, `search_reader`), and `bucket_admin` / `scope_admin`.

Cluster-wide administrative roles — including `cluster_admin`, `backup_admin` and `external_stats_reader` — **cannot** be scoped. Granting one of these is always a cluster-wide grant.

Prefer collection-level grants over bucket-level ones for application service accounts. A bucket-level `data_reader` on a multi-tenant bucket is a data-exposure finding waiting to happen.

## Roles for common use cases

**Application service account (read-write against one collection):**
```
data_reader[orders:sales:invoices]
data_writer[orders:sales:invoices]
query_select[orders:sales:invoices]
query_insert[orders:sales:invoices]
query_update[orders:sales:invoices]
query_delete[orders:sales:invoices]
```

**Read-only reporting:**
```
data_reader[orders]
query_select[orders]
```
Add `analytics_reader` if the account reads through the Analytics Service.

**Index management (CI/CD):**
```
query_manage_index[orders]
```
Grants index DDL without document read access, so a pipeline identity never needs to see data.

**Metrics scraping:**
```
external_stats_reader
```
This is the role for a Prometheus scrape account. It is cluster-wide and carries no data access. Do **not** give a scraper `cluster_admin`.

**DBA / ops:**
```
cluster_admin
```
Cluster management without data access. `full_admin` exists and grants everything including data — keep it for break-glass only.

**Backup agent:**
```
backup_admin
```

**Break-glass data access:**
```
data_reader[*]
query_select[*]
```
Restrict to a named individual, require MFA at the IdP, and make the grant temporary.

## Least-privilege design process

1. **Enumerate the operations the identity performs.** SELECT on these collections; INSERT/UPDATE on those; never DELETE.
2. **Map operations to the narrowest roles** using the roles reference for your release.
3. **Scope to the collection**, not the bucket, wherever the role supports it.
4. **Create a group**, attach the roles to the group, put the identity in the group.
5. **Verify** the effective permissions before the account goes live.

## Group structure for teams

```
Groups:
  app-orders-rw   -> data_reader[orders:sales:invoices], data_writer[orders:sales:invoices],
                     query_select[...], query_insert[...], query_update[...]
  app-orders-ro   -> data_reader[orders:sales:invoices], query_select[orders:sales:invoices]
  reporting       -> query_select[orders]
  dba-ops         -> cluster_admin
  index-deploy    -> query_manage_index[orders], query_manage_index[inventory]
  backup-agent    -> backup_admin
  metrics-scrape  -> external_stats_reader

Users:
  orders-service   -> app-orders-rw
  reporting-user   -> reporting
  alice (DBA)      -> dba-ops
  ci-pipeline      -> index-deploy
  backup-agent     -> backup-agent
  prometheus       -> metrics-scrape
```

## Password policy

The cluster-wide password policy controls minimum length and character-class requirements for **local** users:

```bash
couchbase-cli setting-password-policy -c <host> -u <admin> -p <password> \
  --set --min-length 12 --uppercase 1 --lowercase 1 --digit 1 --special-char 1
```

Read the current policy with `--get`. The REST equivalent is `/settings/passwordPolicy`.

**Couchbase Server has no password-expiry or rotation-interval setting** — the policy controls composition only. Anyone who needs enforced periodic rotation for human accounts must get it from their identity provider via LDAP or SAML, not from Couchbase.

For service accounts, use long generated secrets held in a secrets manager and rotate on compromise or personnel change rather than on a calendar.

## Locking and unlocking users

**8.0+ only.** An administrator can lock a local user account, which prevents authentication and terminates any active sessions immediately:

```bash
couchbase-cli user-manage -c <host> -u <admin> -p <password> --lock   --rbac-username alice
couchbase-cli user-manage -c <host> -u <admin> -p <password> --unlock --rbac-username alice
```

Also 8.0+: `--temporary-password` sets a password the user must change at next login. It applies to local users only.

**Couchbase Server does not implement automatic lockout after N failed login attempts.** Any skill, runbook or audit response that claims a configurable failed-attempt threshold and lockout duration in Couchbase Server is wrong. If your compliance framework requires failed-attempt lockout, you must either put human logins behind an IdP that enforces it (LDAP/SAML) or detect repeated `login failure` audit events (ID 8193) in your SIEM and lock the account through the API.

Locking applies to local users. External users are disabled in the external directory.

## RBAC audit

Quarterly, at minimum:

1. Enumerate all local users and all groups.
2. For each identity, record direct roles plus roles inherited from groups.
3. Compare effective permissions against the documented intent for that identity.
4. Remove service accounts for decommissioned services and users for departed staff.
5. Review group membership — groups accumulate members and rarely shed them.
6. Check that no application account holds a `[*]` grant it does not need.

On 8.0+, the user-activity tracking feature (Enterprise Edition) records the last time a local user made a request to the Cluster Manager, which makes dormant-account detection considerably less manual.
