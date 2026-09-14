# External authentication

## Contents

- [Why external auth](#why-external-auth)
- [LDAP / Active Directory](#ldap--active-directory)
- [SAML](#saml)
- [PAM](#pam)
- [External users in Couchbase](#external-users-in-couchbase)

## Why external auth

Local Couchbase users are appropriate for application service accounts. For human operators, delegating authentication to an identity provider gives you:

- One place to onboard and offboard people
- MFA enforced at the IdP
- Password expiry and complexity policy inherited from the organisation — which matters because Couchbase Server itself has no password-expiry setting
- An authentication audit trail in the IdP as well as in Couchbase

## LDAP / Active Directory

Couchbase Server supports LDAP for authentication (bind) and for mapping LDAP groups onto Couchbase groups. Configure it in the Web Console under **Security → LDAP**, via `couchbase-cli setting-ldap`, or via the LDAP settings REST endpoint.

Settings that matter:

| Setting | Notes |
|---|---|
| Host / port | Use LDAPS (or StartTLS) in production, never plaintext LDAP |
| Encryption + CA | The directory server's CA must be trusted by every Couchbase node |
| Bind DN and password | A read-only service account Couchbase uses to query the directory |
| User DN mapping | Either a template (`uid=%u,ou=people,dc=example,dc=com`) or an LDAP query that resolves a username to a DN |
| Group query | How Couchbase discovers a user's group memberships |
| Cache lifetime | How long authentication and group-membership results are cached |

**Group mapping.** Create a Couchbase group whose name matches (or is mapped to) the LDAP group, attach Couchbase roles to that Couchbase group, and members inherit the roles without any per-user role assignment:

```
LDAP group: cn=couchbase-dba,ou=groups,dc=example,dc=com
        maps to
Couchbase group: dba-ops   (roles: cluster_admin)
```

**Test before you rely on it.** The Web Console has an authentication test for LDAP configuration. The usual failure modes are: a bind DN that the directory rejects, a user DN template that does not match the directory's schema, and an LDAPS certificate the Couchbase nodes do not trust.

Changes to LDAP configuration are audited (`setup ldap`, ID 8227; `modify ldap settings`, ID 8246) and those events are non-filterable.

## SAML

**Available in 7.6+. Enterprise Edition.** SAML 2.0 single sign-on for the **Couchbase Server Web Console only**.

SAML does not cover SDK connections, CLI tools, or REST API calls — those still authenticate with credentials or client certificates. Plan LDAP (or local service accounts) alongside SAML; SAML alone does not secure programmatic access.

Setup, in order:

1. In Couchbase (**Security → SAML**), read the service-provider entity ID and ACS URL that Couchbase will use.
2. Register Couchbase as a SAML service provider in your IdP using those values.
3. Export the IdP metadata and load it into Couchbase (by URL or by pasting the XML).
4. Decide how the SAML assertion identifies the user, and create matching Couchbase users or groups in the `external` domain.
5. Map the IdP's group claim onto Couchbase groups so roles arrive by group membership.

Keep at least one local administrator account that can still log in if the IdP is unreachable, and know how to reach the Web Console with SAML bypassed before you enable it.

## PAM

PAM authentication delegates to the Linux host's PAM stack on each Couchbase node. It is useful where nodes are already joined to a directory through SSSD/Kerberos and you would rather not configure LDAP in Couchbase separately.

The Couchbase user record must exist in the `external` domain with the same username as the OS account. Roles still come from Couchbase (directly or by group).

PAM is less common than LDAP in enterprise deployments; if the organisation already runs Active Directory, LDAP is the better-trodden path.

## External users in Couchbase

Whatever the mechanism (LDAP, SAML, PAM), external users:

- Live in the `external` domain
- Have no password stored in Couchbase
- Still need Couchbase roles — assign them through group membership, not per user
- Cannot be locked with the 8.0+ user-lock feature; disable them in the directory instead

Create them (or rely on group mapping to avoid creating them at all) with:

```bash
couchbase-cli user-manage -c <host> -u <admin> -p <password> \
  --set --auth-domain external --rbac-username alice --user-groups dba-ops
```

Note that no `--rbac-password` is supplied for an external user — supplying one is an error.
