---
name: couchbase-mobile
description: "Design and build mobile, edge, and offline-first applications with Couchbase Lite, Sync Gateway, Couchbase Edge Server, and Capella App Services. Use whenever the user asks about Couchbase Lite, Sync Gateway, App Services, Edge Server, offline-first, mobile sync, data replication to mobile, the replicator, push/pull replication, the sync function or access-and-validation function, channel access, mobile user authentication, conflict resolution and version vectors, iOS/Android/React Native/.NET MAUI Couchbase, peer-to-peer and multipeer sync, Couchbase Lite vector search, or upgrading Couchbase Lite, Sync Gateway, or App Services. Distinct from couchbase-xdcr (server-to-server replication) and couchbase-app-integration (server-side SDKs). Use proactively when the user has a mobile, IoT, field worker, or offline-capable application requirement."
license: Apache-2.0
---

# Couchbase Mobile

A skill for *designing, building, and upgrading* mobile and edge applications with Couchbase Lite plus Sync Gateway / Capella App Services — offline-first sync, channel-based access control, conflict resolution, and mobile-specific patterns.

Distinct from:
- `couchbase-xdcr` — server-to-server replication between Couchbase clusters
- `couchbase-app-integration` — server-side SDK integration (Python, Java, Node.js, etc.)
- `couchbase-capella` — Capella cluster provisioning (App Services runs against a Capella cluster)

## When this skill applies

- "How do I sync data to an iOS / Android app?"
- "How do I build an offline-first app with Couchbase?"
- "What's Couchbase Lite? How does Sync Gateway work?"
- "How do I set up Capella App Services?"
- "How do I control which users see which documents?"
- "How do I handle conflicts in mobile sync?"
- "How do I do peer-to-peer sync between devices?"
- "Can I use vector search in Couchbase Lite?"
- **"How do I upgrade App Services / Sync Gateway / Couchbase Lite, and can I roll back?"**

## Pick the right reference

| Question | Read |
|---|---|
| "Architecture — Lite vs Sync Gateway vs App Services vs Edge Server, when to use which" | `references/architecture.md` |
| "Sync function — channels, access control, routing documents to users" | `references/sync-function.md` |
| "Couchbase Lite — replicator config, conflict resolution, queries, vector search" | `references/couchbase-lite.md` |
| **"Upgrades — App Services 4.x, rollback, metadata migration, version pinning"** | `references/app-services-upgrades.md` |

## Three core principles

**Principle 1 — Channel-based access is the security model.**
Sync Gateway / App Services control data access through channels. A document is routed to one or more channels by the sync function (in App Services, the *Access Control and Data Validation* function); a user has access to a set of channels and receives only documents in those channels. There is no separate row-level security mechanism — per-document access control means per-document or per-group channels.

**Principle 2 — Offline-first means conflicts are inevitable.**
When two devices edit the same document while offline, both changes are valid locally. On sync, a conflict occurs. Couchbase Lite resolves it automatically or via a custom resolver. **The default changed in Lite 4.0:** revision trees and "most active wins" gave way to version vectors and **last-write-wins on hybrid logical clock timestamps**. Design documents assuming conflicts — prefer additive updates (event logs, append-only fields) over destructive in-place updates.

**Principle 3 — The sync function runs on every document mutation.**
It executes server-side for every write, deciding which channels the document belongs to and who may read or write it. Keep it fast and side-effect free. Slow sync functions bottleneck the entire write path.

## Platform support

Couchbase Lite 4.1 documents these platforms (https://docs.couchbase.com/couchbase-lite/current/index.html):

- **Swift** and **Objective-C** (iOS/macOS)
- **Android** (Kotlin, Java)
- **Java** (JVM/desktop/server)
- **C / C++** — as of 4.1 the C++ wrapper API is a committed, supported API surface, not volatile
- **.NET / C#** (including .NET MAUI)
- **Hybrid**: Ionic and React Native. The React Native plugin uses React Native's **Turbo Module** architecture, exposing a TypeScript API over the native database.
- **Couchbase Lite JavaScript 1.0** is a separate product line with its own docs and browser support matrix.

All platforms share the replication protocol and sync semantics; APIs differ by language, concepts do not. Flutter/Dart is not a Couchbase-documented platform — treat any Flutter binding as third-party.

## Current releases (verified September 2026)

Verified against the docs navigation and release notes on docs.couchbase.com in September 2026. Gate version-specific guidance explicitly; mixed fleets are normal in the field, so **do not delete older-version guidance** — label it.

| Component | Current | Notes |
|---|---|---|
| **Couchbase Lite** | **4.1** | Multipeer replicator over BLE *and* Wi-Fi with automatic transport switching; committed C++ API; Windows ARM64 for Lite C; replication correlation ID on all platforms; Kotlin serialization on Android. **You cannot downgrade from 4.1 to earlier Lite versions.** (https://docs.couchbase.com/couchbase-lite/current/cbl-whatsnew.html) |
| **Couchbase Lite JavaScript** | **1.0** | Separate line; can replicate directly with Edge Server where CORS is enabled |
| **Sync Gateway** (self-managed) | **4.1** | Cluster compatibility version for non-disruptive rolling upgrades with a rollback window; distributed resync; channel history management APIs; opt-in metadata isolation. Requires Couchbase Server 7.6+ (7.6.5+ for bidirectional active-active XDCR). (https://docs.couchbase.com/sync-gateway/current/whatsnew.html) |
| **Capella App Services** | **4.1** (August 2026) | 4.0 was October 2025; 4.0.2 December 2025; 4.0.4 April 2026. See `references/app-services-upgrades.md`. (https://docs.couchbase.com/app-services/release-notes/release-notes.html) |
| **Couchbase Edge Server** | **1.1** (June 2026) | Fine-grained per-user access control at database/scope/collection level (opt-in via `enable_user_access_control`); JWT credential rotation without restart; CORS; Windows and Linux ARM64 support. 1.0 shipped March 2025. (https://docs.couchbase.com/couchbase-edge-server/current/introduction/whats-new.html) |
| **Vector Search extension** | **2.0.0** (October 2025) for Couchbase Lite 4.0.0 | Enterprise Edition only, shipped as a separate extension library. See `references/couchbase-lite.md`. |

## Capella App Services vs self-managed Sync Gateway

| | Capella App Services | Self-managed Sync Gateway |
|---|---|---|
| Management | Fully managed by Couchbase | You manage install, config, and upgrades |
| Setup time | Minutes | Hours to days |
| Scaling | Scale nodes/compute through the UI or Management API (2–12 nodes) | Manual |
| Upgrades | Self-service scheduling of Couchbase-published maintenance jobs; you do not choose the version | Rolling upgrades you drive, with a cluster-compatibility-version rollback window |
| Sync function | Access Control and Data Validation function via UI or Management API, with a Test Function panel (May 2026) | Full config-file control |
| Rollback | **Not documented — see `references/app-services-upgrades.md`** | Rollback window during a 4.1 rolling upgrade via the compatibility-version freeze |
| Use when | On Capella; minimal ops overhead | On-prem, or you need specific config or upgrade control |

For new projects on Capella: use App Services. For self-managed Couchbase Server: use Sync Gateway. For an on-site tier between devices and the cloud: add Edge Server.

## Related skills

- `couchbase-capella` — provisioning the Capella cluster App Services connects to
- `couchbase-data-modeling` — document design, especially channel design and conflict-resistant shapes
- `couchbase-security-hardening` — Sync Gateway TLS and authentication configuration
- `couchbase-xdcr` — bidirectional XDCR between mobile clusters (Sync Gateway 4.0+)
