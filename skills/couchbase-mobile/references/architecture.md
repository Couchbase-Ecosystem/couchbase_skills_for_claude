# Mobile architecture

Verified against docs.couchbase.com in September 2026. Version-sensitive claims are gated inline.

## Contents

- [Component overview](#component-overview)
- [When you need each component](#when-you-need-each-component)
- [Replication modes](#replication-modes)
- [Continuous vs one-shot replication](#continuous-vs-one-shot-replication)
- [Authentication](#authentication)
- [Collection-aware sync](#collection-aware-sync)
- [Peer-to-peer sync](#peer-to-peer-sync)
- [Upgrades and version compatibility](#upgrades-and-version-compatibility)

## Component overview

```
Mobile / Edge Device
  └── Couchbase Lite (embedded database)
        └── Replicator (sync protocol)
              ↕ WebSocket (blip protocol)
        Sync Gateway / Capella App Services
              ↕ REST / internal
        Couchbase Server / Capella Cluster
              └── Buckets / Scopes / Collections
```

**Couchbase Lite** — the embedded NoSQL database that runs inside your mobile or edge app. Stores data locally, enables offline operation, runs queries, and manages replication to/from Sync Gateway.

**Sync Gateway** — the middle tier. Handles authentication, channel-based access control, conflict resolution, and the WebSocket replication protocol. Does not store data permanently — it's a gateway into Couchbase Server.

**Capella App Services** — fully managed Sync Gateway hosted by Couchbase on Capella. Each App Services deployment runs a specific Sync Gateway build underneath; the App Services release notes name both (for example, App Services 4.0.4 deploys Sync Gateway 4.0.4). Current version: **4.1** (August 2026).

**Couchbase Edge Server** — an optional on-site tier between Couchbase Lite devices and the cloud. It offers a REST API, queries, and sync both upstream (to App Services / Sync Gateway) and downstream (to Couchbase Lite and other Edge Servers). Current version: **1.1** (June 2026), which adds opt-in per-user access control at the database, scope, and collection level (`enable_user_access_control`), JWT credential rotation without restart, CORS (enabling browser and Couchbase Lite JavaScript clients to replicate directly with it), and Windows plus Linux ARM64 support. (https://docs.couchbase.com/couchbase-edge-server/current/introduction/whats-new.html)

## When you need each component

**Couchbase Lite alone (no sync):** offline-only app with no server synchronization. Local storage and queries only. Use as an embedded database for settings, cached data, or truly offline scenarios.

**Couchbase Lite + Sync Gateway / App Services:** the standard mobile stack. Devices sync with the server. Multiple devices share data. Works offline; syncs when connected.

**Sync Gateway without Couchbase Lite:** some IoT or edge scenarios use the REST API directly on devices that can't embed Couchbase Lite. Less common.

## Replication modes

**Push:** device sends local changes to the server. Use for: data capture devices, sensor uploads, form submissions.

**Pull:** device receives changes from the server. Use for: read-only displays, configuration distribution, content delivery.

**Push + Pull (bidirectional):** device both sends and receives. Use for: collaborative apps, field worker apps, anything where the device both reads and writes shared data.

```swift
// Swift — configure replicator
let config = ReplicatorConfiguration(target: URLEndpoint(url: appServiceURL))
config.replicatorType = .pushAndPull     // or .push / .pull
config.continuous = true                 // continuous: stay connected and sync in real time
                                         // false: one-shot sync then disconnect

let replicator = Replicator(config: config)
replicator.start()
```

## Continuous vs one-shot replication

**Continuous:** maintains a persistent WebSocket connection. Syncs changes as they happen. Appropriate for: real-time collaborative apps, field workers who need live updates.

**One-shot:** connects, syncs all pending changes, disconnects. Appropriate for: periodic sync on a schedule, battery-sensitive devices, background sync tasks.

For most mobile apps, use continuous replication while the app is in the foreground and one-shot during background refresh.

## Authentication

**Basic auth (username + password):**
Most straightforward. Credentials are managed in Sync Gateway's user database or via OIDC.

```swift
config.authenticator = BasicAuthenticator(username: "alice", password: "password")
```

**Session auth (recommended for production):**
App authenticates against your backend, backend creates a Sync Gateway session, app uses the session token. Avoids storing Couchbase credentials on the device.

```swift
config.authenticator = SessionAuthenticator(sessionID: sessionToken)
```

**OpenID Connect (OIDC):**
Sync Gateway acts as an OIDC relying party. App authenticates via your identity provider (Google, Auth0, Okta, etc.) and Sync Gateway validates the JWT. Best for apps with existing SSO infrastructure.

## Collection-aware sync

Sync Gateway before 3.1 synced at the bucket level. **Sync Gateway / App Services 3.1 and later** sync at collection level. From App Services 3.1.8 onward, configurations previously defined in bucket mode sit under the `_default` scope and collection (https://docs.couchbase.com/app-services/maintenance/upgrading-app-services.html).

**3.x API shown below.** In Couchbase Lite **4.0 and later**, collections must be supplied to the `ReplicatorConfiguration` initializer up front and cannot be added or removed afterwards — see `references/couchbase-lite.md` and https://docs.couchbase.com/couchbase-lite/current/migration.html

```swift
// Configure which collections to sync
let collection = try database.defaultCollection()
let collectionConfig = CollectionConfiguration()
collectionConfig.channels = ["user.\(userId)", "public"]

config.addCollection(collection, config: collectionConfig)
```

On the server side, each collection has its own sync function and channel namespace. This enables fine-grained sync partitioning: one collection for user-specific data, another for shared read-only content.

## Peer-to-peer sync

Couchbase Lite supports direct device-to-device sync without a server, using a local WebSocket listener. Use for offline field teams, device-to-device transfer, and local-network sync without internet.

**Multipeer replicator (Lite 4.x).** Alongside the URL endpoint listener, Couchbase Lite offers a Multipeer Replicator. In **4.1** it gained **Bluetooth Low Energy** as a transport alongside Wi-Fi: configure Wi-Fi only, Bluetooth only, or both. With both enabled, the replicator picks the best available transport per peer, prefers Wi-Fi, falls back to Bluetooth when Wi-Fi is unreachable, and switches back without interrupting active replication. BLE transport uses TLS over L2CAP channels — the same security guarantees as Wi-Fi, with no device pairing required.

Platform requirements for the Bluetooth transport: **iOS 15+** and **Android API 29+**. Available on Swift, Android (Kotlin/Java), and Objective-C. Bluetooth has lower throughput and higher latency than Wi-Fi and degrades as more peers join, so treat Wi-Fi as primary and Bluetooth as fallback. (https://docs.couchbase.com/couchbase-lite/current/cbl-whatsnew.html)

**Version constraint:** Couchbase Lite 4.0+ can only peer-to-peer sync with other 4.0+ instances. Sync attempts with 3.x peers fail with an error.

```swift
// Device acting as listener (passive side)
let listenerConfig = URLEndpointListenerConfiguration(collections: [collection])
listenerConfig.port = 4984
let listener = URLEndpointListener(config: listenerConfig)
try listener.start()

// Device acting as replicator (active side) — same ReplicatorConfiguration
// but pointing to the listener's URL instead of Sync Gateway
```

P2P sync uses the same conflict resolution and document routing as server-based sync.

## Upgrades and version compatibility

Upgrade planning — App Services 4.x behaviour, rollback, the 4.1 sync metadata migration, the Sync Gateway cluster compatibility version, and Lite 3.x vs 4.0 cross-cluster behaviour — lives in `references/app-services-upgrades.md`. Read it before any live upgrade.
