# Capella credentials

Verified against docs.couchbase.com in September 2026. Source URLs inline.

## Contents

- [Two credential planes](#two-credential-planes)
- [Creating cluster access credentials](#creating-cluster-access-credentials)
- [Basic vs advanced access](#basic-vs-advanced-access)
- [Scoping credentials](#scoping-credentials)
- [Rotating credentials](#rotating-credentials)
- [Capella API keys (for automation)](#capella-api-keys-for-automation)
- [App Services credentials](#app-services-credentials)
- [Connection strings](#connection-strings)
- [SDK credential configuration](#sdk-credential-configuration)

## Two credential planes

| Type | Where created | What it's for | In application code? |
|---|---|---|---|
| **Capella account (UI/SSO login)** | cloud.couchbase.com | Managing Capella — clusters, networking, billing. Carries organization and project roles. | Never |
| **Cluster access credentials** | Cluster → Settings → Cluster Access | Application connections to the cluster's data plane | Yes |
| **Organization API keys** | Organization → API Keys | Programmatic management via the Management API v4 | Only in CI/secrets manager |

Your Capella login authenticates you to the management plane and has no data-plane access on its own. Applications authenticate with cluster access credentials, which are scoped to buckets (or finer) and roles.

**Naming note:** the Capella UI now calls these **cluster access credentials** and puts them under **Settings → Cluster Access**. The Management API still exposes them under `Database Credentials` and `Database Roles` endpoints — the same object under its older name. Older docs and older UI builds say "database credentials"; treat the terms as synonyms.

Source: https://docs.couchbase.com/cloud/clusters/manage-database-users.html

## Creating cluster access credentials

**Cluster → Settings → Cluster Access → Create Access**

Fields:

- **Cluster Access Name** — up to 35 characters; may not contain `( ) < > @ , ; : \ " / [ ] ? = { }`. Convention: `<service-name>-<env>`, e.g. `orders-service-prod`.
- **Password** — at least 8 characters with one or more uppercase letters, lowercase letters, numbers, and special characters from `` ^ $ ( ) ? " ! @ # % , ' : _ ~ ` = + - ``. **Auto-generate password** produces a conforming random password. Copy it immediately — Capella will not show it again.
- **Access** — basic or advanced, below.

You need the **Project Owner** or **Cluster Manager** role for the containing project.

## Basic vs advanced access

- **Basic Bucket Level Access** — pick a bucket and a read/write level. Available on every plan.
- **Advanced access credentials** — finer-grained access roles and privileges (scope/collection level). Per the docs, advanced access credentials and access roles **require a paid plan**.

Both are manageable through the Management API: `List/Get/Create Database Credentials` and the `Database Roles` and `List Capella Privileges` endpoints.

## Scoping credentials

Give each service its own credential with the minimum access it needs:

| Service | Buckets | Access |
|---|---|---|
| `orders-service-prod` | orders | Read/Write |
| `reporting-service-prod` | orders, inventory | Read Only |
| `analytics-pipeline-prod` | all | Read Only |

Never share one credential across all services. If one service is compromised, everything it can reach is exposed.

Where the plan allows advanced access credentials, scope to the Scope or Collection rather than the whole Bucket.

## Rotating credentials

There is no in-place password change for a cluster access credential. Rotate by replacement:

1. Create a new credential with the same access configuration.
2. Update the application (rolling deploy, or a secrets-manager update the app re-reads).
3. Verify the application is running on the new credential.
4. Delete the old credential.

Plan this into your rotation procedure — the overlap window is what makes it zero-downtime.

## Capella API keys (for automation)

For Terraform, CI/CD, and any Management API v4 automation:

**Organization → API Keys → Create API Key**

- Keys carry Capella organization and project roles (for example Organization Owner, Project Creator, Organization Member). The Management API reference lists the required roles per endpoint.
- Keys can be restricted with an allowed IP address list.
- **Every API key has an expiration date** — track it, or automation breaks silently on expiry.
- Pass the key as a Bearer token in the HTTP `Authorization` header.

API keys are management plane only. They do not grant data access; they can, however, create cluster access credentials that do.

Store keys in a secrets manager and rotate them on a schedule at least as often as their expiry.

Source: https://docs.couchbase.com/cloud/management-api-guide/management-api-intro.html

## App Services credentials

App Services have their own credential model, separate from the operational cluster's:

- **App Service / App Endpoint admin users** — created via the Management API (`adminUsers` endpoints) or the UI, scoped to a specific App Service or a list of App Endpoints. These reach the Admin and Metrics REST APIs and are gated by the App Service allowed IP list.
- **App users** — the end-user identities your mobile app authenticates as, managed per App Endpoint, with channel-based access. See the `couchbase-mobile` skill.

## Connection strings

Copy the connection string from the cluster's **Connect → SDK** tab rather than constructing it. It is always a `couchbases://` (TLS) URL. The Connect tab also generates a ready-made snippet or full sample per SDK language, pre-populated with the connection string and the selected cluster access name.

With a private endpoint, the same hostname resolves privately once private DNS names are enabled in your VPC — there is no separate documented private hostname template (see `references/networking.md`).

Source: https://docs.couchbase.com/cloud/get-started/connect.html

## SDK credential configuration

```python
# Python
PasswordAuthenticator("cluster-access-name", "cluster-access-password")
```

```java
// Java
PasswordAuthenticator.create("cluster-access-name", "cluster-access-password");
```

```javascript
// Node.js
{ username: "cluster-access-name", password: "cluster-access-password" }
```

Always load credentials from environment variables or a secrets manager — never hardcode them:

```python
import os
auth = PasswordAuthenticator(
    os.environ["CB_USERNAME"],
    os.environ["CB_PASSWORD"],
)
```
