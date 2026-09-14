# Couchbase Lite

Verified against docs.couchbase.com in September 2026 (Couchbase Lite 4.1 docs). Version-sensitive behaviour is gated inline. Source URLs appear next to the claims that need them.

## Contents

- [Opening a database](#opening-a-database)
- [CRUD operations](#crud-operations)
- [Querying with SQL++](#querying-with-sql)
- [Live queries (change listeners)](#live-queries-change-listeners)
- [Document change listeners](#document-change-listeners)
- [Replicator configuration](#replicator-configuration)
- [Conflict resolution](#conflict-resolution)
- [Vector search in Couchbase Lite](#vector-search-in-couchbase-lite)
- [Best practices](#best-practices)

## Opening a database

```swift
// Swift
let config = DatabaseConfiguration()
config.directory = getDocumentsDirectory().path
let database = try Database(name: "myapp", config: config)
let collection = try database.defaultCollection()
```

```kotlin
// Kotlin
val config = DatabaseConfigurationFactory.newConfig()
val database = Database("myapp", config)
val collection = database.defaultCollection
```

```csharp
// .NET / C#
var database = new Database("myapp");
var collection = database.GetDefaultCollection();
```

Couchbase Lite's documented platforms are Swift, Objective-C, Android (Kotlin/Java), Java, C/C++, .NET, and the Ionic and React Native hybrid plugins, plus the separate Couchbase Lite JavaScript product line. There is no Couchbase Lite Python SDK — do not offer one.

## CRUD operations

```swift
// Create / Update
let doc = MutableDocument(id: "user::alice")
doc.setString("Alice Smith", forKey: "name")
doc.setString("alice@example.com", forKey: "email")
doc.setInt(30, forKey: "age")
try collection.save(document: doc)

// Read
if let result = try collection.document(id: "user::alice") {
    let name = result.string(forKey: "name")
}

// Update
if let existing = try collection.document(id: "user::alice")?.toMutable() {
    existing.setInt(31, forKey: "age")
    try collection.save(document: existing)
}

// Delete
if let doc = try collection.document(id: "user::alice") {
    try collection.delete(document: doc)
}
```

## Querying with SQL++

Couchbase Lite supports a SQL++ dialect for querying the local database:

```swift
let query = try database.createQuery(
    "SELECT name, email FROM _ WHERE type = 'user' AND age > 25 ORDER BY name"
)
let results = try query.execute()
for result in results {
    print(result.string(at: 0) ?? "", result.string(at: 1) ?? "")
}
```

```kotlin
val query = database.createQuery(
    "SELECT name, email FROM _ WHERE type = 'user' AND age > 25 ORDER BY name"
)
val results = query.execute()
```

The `_` refers to the default collection. For named collections: `SELECT * FROM myScope.myCollection WHERE ...`

## Live queries (change listeners)

```swift
let query = try database.createQuery("SELECT * FROM _ WHERE type = 'message' ORDER BY timestamp DESC LIMIT 50")
let token = query.addChangeListener { change in
    if let results = change.results {
        // Update UI with new results
        updateMessageList(results.allResults())
    }
}
// Remove listener when done
query.removeChangeListener(withToken: token)
```

Live queries re-execute automatically when underlying data changes. Use for reactive UI updates.

## Document change listeners

```swift
let token = collection.addDocumentChangeListener(id: "user::alice") { change in
    // Document was created, updated, or deleted
    print("Document changed:", change.documentID)
}
```

## Replicator configuration

```swift
let appServiceURL = URL(string: "wss://your-app-service.apps.cloud.couchbase.com/your-endpoint")!
var config = ReplicatorConfiguration(target: URLEndpoint(url: appServiceURL))

// Authentication
config.authenticator = BasicAuthenticator(username: "alice", password: "password")
// Or session auth (preferred):
// config.authenticator = SessionAuthenticator(sessionID: sessionToken)

// Replication type
config.replicatorType = .pushAndPull
config.continuous = true

// Filter — only sync certain documents
config.pushFilter = { (document, flags) -> Bool in
    return document.string(forKey: "type") != "draft"  // don't sync drafts
}

// Collection-level config
var collConfig = CollectionConfiguration()
collConfig.channels = ["user.alice", "public"]
config.addCollection(try database.defaultCollection(), config: collConfig)
// NOTE (4.0+): collections must be supplied up front to the
// ReplicatorConfiguration initializer and can no longer be added or removed
// dynamically. Use ReplicatorConfiguration(collections:target:) instead of the
// 3.x database-based initializer plus addCollection().
// See https://docs.couchbase.com/couchbase-lite/current/migration.html

let replicator = Replicator(config: config)

// Status listener
let token = replicator.addChangeListener { change in
    switch change.status.activity {
    case .connecting: print("Connecting...")
    case .idle: print("Idle — up to date")
    case .busy: print("Syncing...")
    case .offline: print("Offline")
    case .stopped:
        if let error = change.status.error {
            print("Stopped with error:", error)
        }
    }
}

replicator.start()
```

## Conflict resolution

**The default changed in Couchbase Lite 4.0.** Gate this by version:

- **Lite 3.x and earlier** — revision trees, resolved by `"most active wins"`: compare revision generation numbers. Revision IDs look like `<generation>-<document-hash>`.
- **Lite 4.0 and later** — version vectors, resolved by **last-write-wins on hybrid logical clock timestamps**. Revision IDs look like `<timestamp>@<source-id>`. `Document.revisionID` still works and returns the new form; a `timestamp` property exposes the logical timestamp directly.

Migration behaviour (https://docs.couchbase.com/couchbase-lite/current/swift/version-vectors.html): opening a CBL 3.1 or 3.2 database with CBL 4.0 upgrades documents to version vectors **lazily**, as they are accessed and modified. This is one-way — a 3.x Lite cannot open a database that has been upgraded. Lite 4.0 also requires Sync Gateway / App Services 4.0+, and can only peer-to-peer sync with other 4.0+ peers.

Custom resolver (both eras; on 4.0+ you can use `timestamp` in your logic):

```swift
class MyConflictResolver: ConflictResolverProtocol {
    func resolve(conflict: Conflict) -> Document? {
        let local = conflict.localDocument
        let remote = conflict.remoteDocument

        // Return nil to delete the document
        // Return local to keep local version
        // Return remote to keep remote version
        // Return a merged MutableDocument for a custom merge

        // Example: keep the version with the higher score
        let localScore = local?.int(forKey: "score") ?? 0
        let remoteScore = remote?.int(forKey: "score") ?? 0
        return localScore >= remoteScore ? local : remote
    }
}

config.conflictResolver = MyConflictResolver()
```

## Vector search in Couchbase Lite

Verified September 2026 against https://docs.couchbase.com/couchbase-lite/current/swift/vector-search.html, its per-platform siblings, and the Vector Search release notes.

**Availability and gating.** On-device vector search was introduced in Couchbase Lite **3.2** (public beta April 2024, GA thereafter). It ships as a **separate Vector Search extension library**, and it is **Enterprise Edition only** — the install pages say "Enterprise users can also download the Couchbase Lite Vector Search extension library." The current extension is **Vector Search 2.0.0 (October 2025), built for Couchbase Lite 4.0.0** (CBL-7335). Documented on Swift, Objective-C, Android, Java, C, and .NET.

**Query syntax — this changed.** The current function is `APPROX_VECTOR_DISTANCE()`. Older material and pre-GA documentation showed `VECTOR_MATCH()`; that is not the documented API for 3.2+ and should not be used.

```swift
// Create a vector index (Enterprise Edition + Vector Search extension)
let config = VectorIndexConfiguration(expression: "vector", dimensions: 3, centroids: 100)
try collection.createIndex(withName: "vector-idx", config: config)

// Query by approximate vector distance
let query = try database.createQuery(
    "SELECT id, title FROM _ " +
    "ORDER BY approx_vector_distance(vector, $vector) " +
    "LIMIT 5"
)
```

Signature: `APPROX_VECTOR_DISTANCE(vector-expr, target-vector, [metric], [nprobes], [accurate])`. Two constraints from the docs:

- Using a different distance **metric** in the function than the one configured on the index raises an error at query-compile time.
- Like Full Text Search's `match()`, `APPROX_VECTOR_DISTANCE()` and Hybrid Vector Search **cannot be combined with other expressions using `OR`** in the same `WHERE` clause.

Hybrid Vector Search (vector distance combined with other predicates, subject to the `OR` restriction) is supported.

**Dimensions.** Couchbase Lite supports vector dimensions in the range **2–4096**.

**Centroids and probes.** Vectors are clustered by k-means around centroids. Docs guidance: the optimal number of centroids is approximately the **square root of the number of documents**; the number of probes should be at least **8, or 0.5% of the centroid count**, whichever is larger. More centroids means better accuracy and longer index build time.

**Vector encoding (compression).** Configured on the index:

| Encoding | Effect |
|---|---|
| `none` | Highest quality results, highest disk and performance cost |
| Scalar Quantizer (SQ) | Reduces bits per component to **4, 6, or 8**. Couchbase Lite's default is **8-bit (SQ-8)** |
| Product Quantizer (PQ) | Splits vectors into subspaces and quantizes each independently; higher quality than SQ at equivalent compression, at the cost of complexity |

More compression means a smaller, faster index but less accurate distance calculations.

**Lazy vector indexes.** A Couchbase Lite-specific alternative to the standard predictive-model-driven index: your application supplies embeddings on its own schedule through the index updater rather than the index computing them inline. Designed for two cases the docs call out — documents added by end users when no ML model is available yet, and a remote ML model that is unavailable or intermittent, where you skip failed documents and retry later. Lazy indexing is **not automatic**; you must schedule index updates yourself, and updating the index is independent of saving documents.

> Index-update throughput characteristics for the lazy path are not documented. Benchmark on your own target device and model before committing to a specific rate.

On-device vector search is useful for privacy-sensitive applications, fully offline semantic search, RAG at the edge, and recommendation engines that must work without connectivity.

## Best practices

**Always close the database when done.** Especially on mobile where the app may be suspended. Use database lifecycle management tied to the app lifecycle (not individual screens).

**Use document IDs deliberately.** Design IDs like server Couchbase: `type::uuid`. This makes filtering by type via key prefix possible.

**Keep documents small.** Couchbase Lite loads documents into memory for operations. Very large documents (>100KB) slow down sync and query performance.

**Use collections.** Sync specific collections rather than the whole bucket. This reduces the amount of data synced to each device.

**Battery and network.** On mobile, use `continuous: false` for background sync and `continuous: true` only in the foreground. Listen for network reachability changes and pause the replicator when offline.
