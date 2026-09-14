# SDKs — choosing, installing, version awareness

Couchbase ships official SDKs in multiple languages. They share the same underlying protocol but differ in idioms, maturity, and feature coverage. This reference helps pick the right one and avoid common version traps.

> **Never state an SDK version, method name or class name from memory.** Each SDK's own docs at `https://docs.couchbase.com/<sdk>/current/` are the only authority, and they move. Everything below is a pointer to where to look, not a substitute for looking.

## Contents

- [The SDK list](#the-sdk-list)
- [Major version awareness](#major-version-awareness)
- [Install commands by language](#install-commands-by-language)
- [SDK feature parity considerations](#sdk-feature-parity-considerations)
- [Sync vs async clients](#sync-vs-async-clients)
- [Compatibility matrix](#compatibility-matrix)
- [Couchbase Mobile vs server SDKs](#couchbase-mobile-vs-server-sdks)
- [Where to find the docs](#where-to-find-the-docs)
- [Quick decision tree](#quick-decision-tree)

## The SDK list

Officially-supported SDKs. Verify current support status and end-of-life dates on each SDK's project-docs pages before committing to one.

| Language | Artifact | Notes |
|---|---|---|
| Java | `com.couchbase.client:java-client` | Reference SDK — most mature, fullest coverage. Blocking, reactive (Project Reactor) and `CompletableFuture` APIs |
| .NET | `CouchbaseNetClient` (NuGet) | C# / F#; async/await throughout |
| Node.js | `couchbase` (npm) | Promise-based; TypeScript typings shipped |
| Python | `couchbase` (PyPI) | Sync plus `acouchbase` (asyncio) and `txcouchbase` (Twisted) variants |
| Go | `github.com/couchbase/gocb/v2` | Idiomatic Go; `context`-based cancellation |
| C++ | `couchbase-cxx-client` | The modern C++ SDK; also the core underneath several other SDKs |
| C | `libcouchbase` | Low-level; check its current support status before starting new work on it |
| Scala | `com.couchbase.client::scala-client` | Scala idioms over the Java core |
| Kotlin | `com.couchbase.client:kotlin-client` | Coroutine-based |
| Ruby | `couchbase` gem | Verify current status and feature coverage before relying on it |
| PHP | `couchbase` PECL extension | Verify current status and feature coverage before relying on it |
| Swift / Objective-C | Couchbase Lite | **Mobile product, not a server SDK** |

**For brand-new projects:** Java or .NET if your stack supports them — they tend to get features first. Python, Node and Go are all current and well-covered. Scala and Kotlin layer their own idioms over the Java core.

## Major version awareness

The SDKs have had significant API transitions, and stale tutorials are everywhere. **Establish the user's SDK version before giving them code.**

Major-version generations, as documented on each SDK's own pages at the time of writing — re-check rather than quoting these:

| SDK | Current major generation | Older patterns to avoid |
|---|---|---|
| Java | 3.x | 2.x used different APIs (`cluster.openBucket` → `cluster.bucket`) |
| .NET | 3.x | 2.x used different connection patterns and DI conventions |
| Node | 4.x | 3.x and earlier differ substantially |
| Python | 4.x | 3.x was a rewrite from 2.x; 2.x docs are actively misleading today |
| Go | `gocb/v2` | `gocb` v1 had entirely different APIs |

Do not pin minor versions in guidance — they change constantly. State the major generation and point at the SDK's release notes.

**If the user cites a code snippet that doesn't match current docs:** ask which SDK version they're on before "correcting" it.

## Install commands by language

Use the current version from the SDK's own release-notes page in place of the placeholders below.

**Java (Maven):**
```xml
<dependency>
  <groupId>com.couchbase.client</groupId>
  <artifactId>java-client</artifactId>
  <version><!-- current 3.x from the Java SDK release notes --></version>
</dependency>
```

**Java (Gradle):**
```gradle
implementation 'com.couchbase.client:java-client:<current 3.x>'
```

**.NET (NuGet):**
```bash
dotnet add package CouchbaseNetClient
```

**Node.js:**
```bash
npm install couchbase
```

**Python:**
```bash
pip install couchbase
```

**Go:**
```bash
go get github.com/couchbase/gocb/v2
```

**Scala (sbt):**
```scala
libraryDependencies += "com.couchbase.client" %% "scala-client" % "<current version>"
```

**Kotlin (Gradle):**
```gradle
implementation 'com.couchbase.client:kotlin-client:<current version>'
```

Always take the version from the SDK's own release-notes page — these change frequently and any number written into a document like this one is stale the week after it's written.

## SDK feature parity considerations

Most data operations (KV, SQL++ query, Search) are available in all official SDKs. Newer features land unevenly, so **check the specific SDK's release notes rather than assuming parity.**

What is documented at the server level:

- **Distributed ACID transactions** — documented for the C++, .NET, Go, Java, Kotlin, Node.js, PHP, Python and Scala SDKs ([Transactions](https://docs.couchbase.com/server/current/learn/data/transactions.html)). Ruby is not on that list
- **Vector search** — Couchbase Server 8.0 introduces Hyperscale, Composite and Search vector indexes, with SQL++ vector functions (`APPROX_VECTOR_DISTANCE`, `VECTOR_DISTANCE`, `ISVECTOR`, `ENCODE_VECTOR`, `DECODE_VECTOR`, `NORMALIZE_VECTOR`). SDK-side support for vector search arrived over the course of the 7.6 and 8.0 cycles and differs by SDK — verify against the specific SDK
- **Eventing function management** — server-side; managed through the REST API / management surface, not typically an SDK data-plane feature
- **Capella control plane** — not an SDK feature. Use the Capella Management API

If asked "can my SDK do X?" for a recent feature, the honest answer is "let's check that SDK's release notes" — not a remembered matrix.

## Sync vs async clients

Several SDKs offer both sync and async APIs:

**Java:** Three flavors — blocking, reactive (Project Reactor), async (CompletableFuture). Pick reactive for high-throughput servers, blocking for batch jobs.

**.NET:** Async throughout in the 3.x line. Use `Task` / `async`/`await`; `IAsyncEnumerable` for streaming query rows.

**Node.js:** Promise-based throughout; works with async/await.

**Python:** Three flavors — sync (default), asyncio (`acouchbase`), Twisted (`txcouchbase`). Pick asyncio for modern Python servers, sync for scripts and batch jobs.

**Go:** Single API with context for cancellation — no separate sync/async APIs.

**Recommendation:** match your application's existing pattern. A FastAPI Python service should use `acouchbase`; a Click CLI tool can use sync `couchbase`. Mixing within one component is awkward; mixing across components is fine.

## Compatibility matrix

**Do not take a compatibility matrix from this file.** Every SDK publishes its own, at `https://docs.couchbase.com/<sdk>/current/project-docs/compatibility.html`, and that is the one to cite. As an example of what those pages look like: the .NET SDK 3.9 compatibility matrix lists support for Couchbase Server 7.0–7.2, 7.6 and 8.0.

The general shape holds across SDKs:

- The SDK negotiates protocol features with the server, so a **recent SDK against a slightly older server** is generally fine
- An **old SDK against a new server** will connect but miss newer features
- **Capella** tracks recent server releases; use a current SDK
- Check the **End of Life dates** page for the SDK before committing to a version in a long-lived system

Both Couchbase Server 7.x and 8.x are in production use. Gate advice explicitly — say "8.0+ only" or "available in 7.1+" rather than assuming the user is on the newest release.

## Couchbase Mobile vs server SDKs

Don't confuse these:

- **Server SDKs** (this reference): connect application servers to a Couchbase cluster
- **Couchbase Mobile / Lite / App Services**: a separate product for mobile apps with offline-first sync

If the user mentions "Couchbase Lite," "Sync Gateway," "App Services," or mobile/offline patterns — that's the mobile product line, not what this skill covers. Refer them to https://docs.couchbase.com/couchbase-lite/current/.

## Where to find the docs

- **All SDK docs:** https://docs.couchbase.com → click your SDK in the sidebar
- **API reference:** linked from each SDK's docs sidebar (for example, the Python client API reference under `https://docs.couchbase.com/sdk-api/couchbase-python-client/`)
- **Compatibility + EOL:** each SDK's `project-docs/compatibility.html` and end-of-life pages
- **GitHub repos:** searchable; useful for examples and issue tracker
- **Release notes:** announce new features and behavioral changes; worth scanning when upgrading

## Quick decision tree

- **Java / Spring / enterprise?** → Java SDK (reactive flavor for servers, blocking for batch)
- **.NET / ASP.NET?** → .NET SDK
- **Node.js?** → Node SDK (always async)
- **Python web service?** → asyncio variant (`acouchbase`)
- **Python script / batch?** → sync `couchbase`
- **Go?** → gocb v2
- **Scala?** → Scala SDK (wraps Java; Scala idioms)
- **Kotlin?** → Kotlin SDK (coroutines)
- **Mobile or offline-first?** → Couchbase Lite (different product line)
- **C or C++?** → the modern C++ SDK for new work; check `libcouchbase`'s current status before starting new C work
- **Code snippet looks wrong?** → check the SDK version before "fixing" it; old tutorials are out of date
- **Need a version number, method name or class name?** → look it up in that SDK's current docs. Do not supply one from memory
