# App Services, Sync Gateway, and Couchbase Lite upgrades

Every claim here was verified against docs.couchbase.com in **September 2026**, with the exact page cited. Where the documentation is silent, this file says so explicitly rather than inferring. Treat "the docs are silent" as a question for Couchbase Support, not as a licence to assume.

## Contents

- [Version landscape](#version-landscape)
- [1. Can Capella App Services be downgraded or reverted?](#1-can-capella-app-services-be-downgraded-or-reverted)
- [2. Management API v4 and the App Services version field](#2-management-api-v4-and-the-app-services-version-field)
- [3. App Services 4.1 sync metadata isolation](#3-app-services-41-sync-metadata-isolation)
- [4. Couchbase Lite 3.x vs 4.0 across clusters and endpoints](#4-couchbase-lite-3x-vs-40-across-clusters-and-endpoints)
- [5. Sync Gateway cluster compatibility version and the freeze](#5-sync-gateway-cluster-compatibility-version-and-the-freeze)
- [Server compatibility](#server-compatibility)
- [Pre-upgrade checklist](#pre-upgrade-checklist)

## Version landscape

| Component | Version | Date | Source |
|---|---|---|---|
| Capella App Services | **4.1** | August 2026 | https://docs.couchbase.com/app-services/release-notes/release-notes.html |
| Capella App Services | 4.0.4 | April 2026 | same |
| Capella App Services | 4.0.2 | December 2025 | same |
| Capella App Services | 4.0 | October 2025 | same |
| Sync Gateway (self-managed) | **4.1** | 2026 | https://docs.couchbase.com/sync-gateway/current/whatsnew.html |
| Couchbase Lite | **4.1** | 2026 | https://docs.couchbase.com/couchbase-lite/current/cbl-whatsnew.html |

App Services deployments run a Sync Gateway build underneath; release notes name both (for example, "New App Services deployments now deploy Sync Gateway 4.0.4"). The 3.x line is still maintained in parallel — Sync Gateway 3.3.4 shipped alongside 4.0.4 in April 2026.

## 1. Can Capella App Services be downgraded or reverted?

**Short answer: no documented downgrade, rollback, or version-revert path exists for Capella App Services. Plan upgrades as one-way.**

What the documentation actually says:

- The **Upgrade App Services** page (https://docs.couchbase.com/app-services/maintenance/upgrading-app-services.html) covers *only* scheduling, deferring, rescheduling, and cancelling maintenance jobs. It describes major, minor, and patch releases, notes that Capella keeps you on the latest patch of your framework version, and that maintenance jobs cannot be deferred indefinitely (each has a latest possible upgrade date). **It contains no downgrade, rollback, or revert procedure, and no statement that one exists.**
- The **App Services release notes** contain no downgrade information for any release.
- The **Management API v4** has no endpoint that changes an App Service's version, and no `version` field on the update request (see section 2).
- On the self-managed side the equivalent statement is explicit, in **Sync Gateway 4.1's** docs: *"Downgrading from Sync Gateway 4.1 to an earlier version is not supported after the full cluster has been upgraded."* (https://docs.couchbase.com/sync-gateway/current/whatsnew.html) and *"Downgrading after the full cluster has been upgraded is not supported."* (https://docs.couchbase.com/sync-gateway/current/cluster-compatibility-version.html)

**Where the docs are silent:** Capella App Services documentation never states, in either direction, whether Couchbase Support can revert an App Service to a prior version out-of-band. It is not offered as a self-service capability anywhere in the UI, the Management API, or the upgrade documentation. If a customer's runbook depends on a rollback, get that answer from Couchbase Support in writing before the upgrade window — do not plan around an undocumented capability.

**Practical consequence for a runbook:** the recoverable unit is not the App Service version. Build the rollback plan around the things you *can* control — deferring the maintenance job until the application is ready, taking a cluster backup before the window, and keeping client versions compatible with both sides (see sections 4 and 5).

## 2. Management API v4 and the App Services version field

**Confirmed: the Management API v4 accepts an App Services version only at create time.**

From the Capella Management API reference OpenAPI document (https://docs.couchbase.com/cloud/management-api-reference/index.html), verified September 2026:

`CreateAppServicerRequest` — body of `POST /v4/organizations/{organizationId}/projects/{projectId}/clusters/{clusterId}/appservices`:

| Field | Required | Description (verbatim from the spec) |
|---|---|---|
| `name` | yes | Name of the cluster (up to 256 characters). |
| `description` | no | A short description of the App Service. |
| `nodes` | no | Number of nodes configured for the App Service. The number of nodes can range from 2 to 12. |
| `compute` | no | `AppServiceCompute` |
| **`version`** | **no** | **"The version of the App Service server. If left empty, it will be defaulted to the latest available version."** |
| `loadBalancerCidr` | no | Pins the load balancer subnet CIDR. **Azure only**; rejected for other providers. |

`UpdateAppServiceRequest` — body of `PUT .../appservices/{appServiceId}`:

| Field | Required |
|---|---|
| `nodes` | yes |
| `compute` | yes |
| `loadBalancerCidr` | no — *"Optional and immutable… It cannot be changed after creation; supplying a different value returns a validation error."* |

**There is no `version` field on the update request.** So:

- You can pin an App Service to a specific version **at creation** by sending `version`.
- Omitting `version` at creation gets you the latest available version.
- There is **no API path to change the version afterwards**, in either direction. Version movement happens only through Capella-scheduled maintenance jobs.
- `loadBalancerCidr` is likewise create-time only (Azure), and the API says so explicitly — a useful contrast: where a field really is immutable-after-create, the spec says so. The `version` field simply does not appear on update at all.

The Management API base URL is `https://cloudapi.cloud.couchbase.com`, paths under `/v4`; the OpenAPI document reports `info.version: v4.0`. **v4 is current as of September 2026.** (https://docs.couchbase.com/app-services/management-api-guide/management-api-use.html)

## 3. App Services 4.1 sync metadata isolation

This is the single item most likely to break a live customer on an App Services 4.x upgrade, and **Capella behaves differently from self-managed Sync Gateway.** Read both columns.

| | **Capella App Services 4.1** | **Self-managed Sync Gateway 4.1** |
|---|---|---|
| Trigger | **Automatic.** *"When you upgrade an existing App Services deployment to 4.1… the migration runs automatically as a background process."* | **Opt-in only.** *"This migration is opt-in and is never applied automatically at upgrade. Your existing deployment is unaffected until you enable the feature."* |
| Destination | A dedicated **mobile system collection** (`_system._mobile` on the Sync Gateway side) | `_system._mobile` |
| Downtime | None; App Services operations continue | None; databases stay readable and writable throughout |
| Reversible? | **No.** *"Migrating sync metadata to the mobile system collection is irreversible."* | **No.** *"The opt-in configuration flags are one-way. Once enabled, the migration cannot be reversed. There is no supported path to move metadata back to `_default._default`."* |
| Opt-out? | **Yes, but only via Couchbase Support, and only before/during the upgrade.** *"Contact Couchbase Support… to opt-out of the migration during the upgrade. If you opt-out, you can trigger the migration at any time after upgrade."* | Opt-in by definition — doing nothing is the opt-out |
| Re-enable later | UI: **App Services → Settings → Sync Metadata Isolation → Migrate sync metadata to mobile system collection → Save**. Applies to **all App Endpoints** in the App Service; cannot be done per endpoint. Also available via the Management API. | Set `use_system_metadata_collection` in the bootstrap config (cluster gate) and in each database config; migration starts automatically once the config is confirmed on all nodes |

Sources: https://docs.couchbase.com/app-services/migrating/migrate-sync-metadata.html (Capella), https://docs.couchbase.com/sync-gateway/current/migrate-metadata-system-collection.html (self-managed), https://docs.couchbase.com/app-services/release-notes/release-notes.html (June 2026 entry).

**Who breaks.** Anything that reads Sync Gateway system metadata out of `_default`:

> *"If you have custom integrations, Eventing functions, or queries that reference sync metadata in the `_default` collection, you must update them to reference the new system collection location."*

The Capella docs also warn that the mobile system collection is **managed exclusively by App Services** — do not read, modify, or delete its contents from applications, queries, or tooling.

**What moves** (self-managed list, which describes the same metadata set): user, role, and email index documents; session documents (TTL preserved); replication state and status documents; DCP checkpoint documents; background-process heartbeat and status documents; database state documents; and Sync Gateway configuration documents.

**What does not move:** collection-scoped document data (`_sync:rev:*`, `_sync:att*:*`) and metadata belonging to sibling databases on the same bucket. Bucket-level bootstrap documents (`_sync:registry`, database config docs) move only after every database on the bucket has finished migrating.

**During migration** Sync Gateway reads `_system._mobile` first and falls back to `_default._default` for keys not yet migrated; writes go to `_system._mobile` from the moment opt-in applies. Once complete the fallback read path is disabled.

**Opting back in via the API.** The Management API exposes `GET|PUT /v4/organizations/{organizationId}/projects/{projectId}/clusters/{clusterId}/appservices/{appServiceId}/metadataIsolation`. The PUT operation is documented as *"Opt an App Service back in to system metadata collection (metadata isolation) after a support-initiated opt-out. Only the value `true` is accepted, and opting back in is permanent: once enabled the App Service cannot be opted out again. Requires App Services version 4.1 or later. New App Services are opted in automatically and existing App Services are opted in on upgrade to 4.1, so this endpoint is only useful after a previous opt-out via Couchbase support."*

**Runbook shape.** Inventory every Eventing function, SQL++ query, external integration, and ops script that touches the App Service's bucket and looks for `_sync:` documents in `_default`. If any exist and cannot be updated before the maintenance window, contact Couchbase Support **before** the upgrade to opt out, remediate, and then trigger the migration from Settings. After the migration there is no way back.

## 4. Couchbase Lite 3.x vs 4.0 across clusters and endpoints

The relevant mechanism is **version vectors**, which replaced revision trees in Lite 4.0 and Sync Gateway 4.0.

What the docs state:

- **Revision trees carried cluster-specific metadata.** *"Each cluster maintained its own revision tree, making it impossible to preserve revision history when documents replicated between clusters."* (https://docs.couchbase.com/sync-gateway/current/server-compatibility/server-compatibility-xdcr-mobile.html)
- **Version vectors travel with the document.** *"The version vector metadata travels with documents during replication, ensuring that revision history remains intact regardless of which cluster processes the document."* Each Couchbase Lite instance is its own component in the vector; Sync Gateway and XDCR act for the cluster's bucket.
- **The explicit client claim, from the App Services 4.0 release note (October 2025):** *"Couchbase Lite clients on v4.0 can seamlessly switch between App Services clusters running this version."* This is stated in the context of bidirectional XDCR between two active App Services clusters for active-standby failover. (https://docs.couchbase.com/app-services/release-notes/release-notes.html)
- **Hard compatibility rules for Lite 4.0** (https://docs.couchbase.com/couchbase-lite/current/swift/version-vectors.html):
  - *"CBL 4.0 requires Sync Gateway 4.0 or later. Attempting to sync with older Sync Gateway versions results in an error."* The Sync Gateway compatibility matrix reinforces this: **"Couchbase Lite 4.0 with Sync Gateway 3.2.0 and 3.3.0 is unsupported."**
  - *"CBL 4.0 can only perform peer-to-peer sync with other CBL 4.0+ instances. Sync attempts with CBL 3.x peers fail with an appropriate error message."*
  - Opening a CBL 3.1 or 3.2 database with CBL 4.0 **automatically upgrades** documents to version vectors, lazily as documents are accessed and modified.
  - *"No Downgrade — version vector upgrades prevent CBL 3.x versions from opening these databases."* And separately, for 4.1: *"You cannot downgrade from 4.1 to earlier versions of Couchbase Lite."*
- **Conflict resolution default changed.** 3.x revision trees used "most active wins" by revision generation; 4.0 uses **last-write-wins on hybrid logical clock timestamps**. A `timestamp` property is exposed on documents; `revisionID` still works but returns the new `<timestamp>@<source-id>` form instead of `<generation>-<hash>`.

**Where the docs are silent — read this carefully.** The documentation states affirmatively that **Lite 4.0 clients can seamlessly switch between App Services clusters running 4.0**. It does **not** contain a corresponding explicit statement about what a **Lite 3.x** client does when repointed at a different cluster or App Endpoint. The mechanism section explains *why* it would not work — 3.x revision trees are cluster-local and cannot preserve revision history across clusters — but the docs do not spell out the failure mode (full resync, conflict storm, or error). Do not assert a specific 3.x behaviour to a customer. Test it against the actual fleet, or ask Couchbase Support.

**Runbook shape.** A cross-cluster failover or endpoint-swap design needs **Couchbase Lite 4.0+ clients against Sync Gateway / App Services 4.0+ on both sides**, plus `enableCrossClusterVersioning=true` on the participating buckets and Couchbase Server 7.6.5+ (7.6.6+ per the App Services 4.0 note) for bidirectional XDCR. A 3.x client fleet is not a supported basis for that design.

## 5. Sync Gateway cluster compatibility version and the freeze

**Introduced in Sync Gateway 4.1.** It is a cluster-wide value that coordinates behaviour across nodes running different versions during a rolling upgrade, and it is the mechanism that gives self-managed deployments a rollback window. (https://docs.couchbase.com/sync-gateway/current/cluster-compatibility-version.html)

How it works:

- Without a freeze, the value is always the **minimum version across all live nodes**. It advances as older nodes are replaced.
- Sync Gateway gates cluster-wide feature activation on it: features that could break older nodes stay inactive until the compatibility version reaches the version that introduced them. Node-local improvements (caching, read-only paths, bug fixes, performance) activate immediately per node.
- **Freezing** pins the value at its current level regardless of which nodes you upgrade, which preserves the option to roll back an upgraded node *"without data loss or invasive data operations such as bucket flushing or backup and restore."*
- A freeze is **cluster-wide, stored in the cluster, and persists across node restarts. It never clears automatically** — you must call unfreeze, even after every node has reached the new version.
- **Rollback is only possible while the freeze is in effect and at least one node is still on the previous version.** After unfreeze and a completed cluster-wide upgrade, downgrade is not supported.

Endpoints, all on the **Sync Gateway Admin REST API**, requiring the **Sync Gateway Dev Ops** RBAC role:

| Endpoint | Purpose |
|---|---|
| `GET /_cluster_compat_version` | Current cluster value, per-node versions, and the frozen value if a freeze is active |
| `POST /_cluster_compat_version/freeze` | Pin at the current value. Response gains `frozen_cluster_compat_version` |
| `POST /_cluster_compat_version/unfreeze` | Clear the pin. Returns 503 with current state if it did not fully apply — retry |

**Is it exposed in Capella App Services? No — and this is a checked negative, not an assumption.**

- `_cluster_compat_version` appears **95 times** in the Sync Gateway Admin REST API reference (https://docs.couchbase.com/sync-gateway/current/rest-api/rest_api_admin.html).
- It appears **zero times** in the Capella App Services Admin REST API reference (https://docs.couchbase.com/app-services/references/rest_api_admin.html). Neither does the 4.1 metadata-migration endpoint `_metadata_migration`.
- There is no cluster-compatibility-version surface in the App Services Management API v4, in the Upgrade App Services page, or in the App Services release notes.

This is coherent with the product shape: in Capella, Couchbase performs the node-level rolling upgrade for you as a maintenance job, so the operator-facing freeze/unfreeze controls are not surfaced. The consequence for a customer runbook is blunt — **on Capella App Services you do not get the Sync Gateway 4.1 rollback window.** Your control is the maintenance-job schedule, not a compatibility freeze.

## Server compatibility

From the Sync Gateway compatibility matrix (https://docs.couchbase.com/sync-gateway/current/product-notes/compatibility.html) and the App Services release notes:

- Sync Gateway **4.0 and 4.1** support Couchbase Server **7.6, 7.6.4, 7.6.5, and 8.0**. Not 7.2 or 7.1.
- **Bidirectional active-active XDCR** on Sync Gateway 4.0/4.1 requires Couchbase Server **7.6.5 or later** per the matrix; the App Services 4.0 release note states **7.6.6** as the minimum for that capability on App Services. App Services 4.0 overall is stated as compatible with Couchbase Server **7.6.4 and above**.
- Sync Gateway 3.x supports the older Server lines (7.1, 7.2 and up) and remains the path for clusters that cannot move to 7.6+.
- Sync Gateway 4.0+ is **not** compatible with Couchbase Server 5.0–7.0.
- Use only **Couchbase** bucket types with Couchbase Mobile — Ephemeral and Memcached buckets are unsupported.

## Pre-upgrade checklist

For a Capella App Services 4.0 → 4.1 upgrade:

1. **Confirm the rollback position.** There is no documented self-service downgrade. Get Support's written answer on out-of-band revert before the window if the customer's plan needs one.
2. **Inventory `_default` sync-metadata consumers.** Eventing functions, SQL++ queries, external integrations, ops scripts. Anything reading `_sync:` documents from `_default` must move to the mobile system collection — or you must opt out via Support before the upgrade.
3. **Decide opt-in vs opt-out on metadata isolation, before the window.** Opting out is Support-only and time-bounded to the upgrade; opting back in later is UI/API self-service, applies to all App Endpoints at once, and is permanent.
4. **Take a cluster backup** of the underlying Capella cluster before the maintenance job.
5. **Check Couchbase Server version** against the matrix above, especially if XDCR is involved.
6. **Check the Couchbase Lite fleet.** Lite 4.x requires Sync Gateway / App Services 4.0+. Lite 4.0 cannot peer-to-peer with 3.x. Lite databases upgraded to version vectors cannot be opened by older Lite versions.
7. **Schedule the maintenance job** rather than letting it land unattended — but note each job has a latest possible upgrade date and cannot be deferred indefinitely.
8. **After the upgrade**, verify the metadata migration state (UI Settings → Sync Metadata Isolation, or the `metadataIsolation` Management API endpoint) and re-test anything that reads bucket contents directly.
