# Eventing function authoring

## Contents

- [Handlers](#handlers)
- [Bindings](#bindings)
- [Basic keyspace accessors](#basic-keyspace-accessors)
- [Advanced keyspace accessors and wildcards](#advanced-keyspace-accessors-and-wildcards)
- [Timers](#timers)
- [SQL++ inside handlers](#sql-inside-handlers)
- [curl() for external HTTP calls](#curl-for-external-http-calls)
- [Logging](#logging)
- [What the JavaScript runtime does NOT support](#what-the-javascript-runtime-does-not-support)
- [Error handling patterns](#error-handling-patterns)
- [Handler performance](#handler-performance)
- [Mutation deduplication — what your handler actually sees](#mutation-deduplication--what-your-handler-actually-sees)
- [Built-in functions](#built-in-functions)

## Handlers

```javascript
function OnUpdate(doc, meta) {
    // Called when a document is created or modified in the Listen To Location.
    // doc  — the document as a JS object
    // meta — document ID, CAS, expiration date, data type
}

function OnDelete(meta, options) {
    // Called when a document is deleted OR expires.
    // options.expired is true when the document expired rather than being deleted.
    if (options.expired) { /* TTL expiry */ } else { /* explicit delete */ }
}

function OnDeploy(action) {          // Couchbase Server 8.0+
    // Runs once when the function is deployed or resumed, before any mutations.
    // action indicates 'deploy' or 'resume'; a delay value in milliseconds
    // reports the time since the function was paused (0 for a deployment).
}
```

All handlers are optional. `OnDeploy` supports the same JavaScript capabilities as `OnUpdate` and `OnDelete`, and is the right place for one-time setup such as registering a timer or initialising resources. Avoid long-running work in it — it has its own OnDeploy Timeout (default 60 s), and a failure means no mutations are processed and the function reverts to its previous state.

Timer callbacks are the fourth entry point; see [Timers](#timers).

Source: [Eventing Terminology](https://docs.couchbase.com/server/current/eventing/eventing-Terminologies.html)

## Bindings

A binding maps an environment-specific artefact to a symbolic name in the function's global space, so the same code moves between environments unchanged. Binding names must be valid JavaScript identifiers and must not collide with built-in types. Three types:

- **Bucket alias** — gives the function access to a `bucket.scope.collection` keyspace, which appears as a JavaScript map. The access level is **read only** or **read and write** (`"r"` / `"rw"` in the exported function definition). Read-only is the right choice for reference-data lookups. **You need at least one bucket alias for a function to touch the Data Service at all.**
- **URL alias** — the endpoint, protocol, credentials, cookie setting, and certificate-validation setting used by `curl()`. Authorization types are no auth, basic, bearer, and digest. The target of a URL alias should not be a node in the Couchbase cluster.
- **Constant alias** — a named integer, decimal, string, boolean, or JSON object, available as a global constant. This is how you get global constants despite global variables being unsupported; an alias `debug` with value `true` behaves exactly like `const debug = true`.

## Basic keyspace accessors

A bucket alias is a JavaScript map. `operator[]` maps to Data Service GET, SET, and DELETE:

```javascript
function OnUpdate(doc, meta) {
    var val = dest[meta.id];              // GET  — returns undefined if absent
    dest[meta.id] = { status: 3 };        // SET  — replaces any existing value
    delete dest[meta.id];                 // DELETE — no-op if absent
}
```

A GET of a non-existent document returns `undefined`; it does not throw. All three throw if the underlying KV operation fails unexpectedly.

## Advanced keyspace accessors and wildcards

A function can listen to multiple collections by using `*` for the scope and/or collection in the Listen To Location (7.1.1+). Bucket aliases can use `*` too.

**If a bucket alias has a `*` wildcard for its scope or collection, basic keyspace accessors do not work** — you must use the Advanced Keyspace Accessors, which expose a wider option and return-value surface. See [Advanced Keyspace Accessors](https://docs.couchbase.com/server/current/eventing/eventing-advanced-keyspace-accessors.html).

## Timers

Enterprise Edition. Timers are the supported way to get limited asynchrony, since `setTimeout` and other asynchronous flows are unsupported.

```javascript
createTimer(callback, date, reference, context)
cancelTimer(callback, reference)
```

- **`callback`** — a **top-level** function taking a single argument, the context.
- **`date`** — a JavaScript `Date` object, which **must be in the future**; otherwise the behaviour is unspecified. It is not a Unix timestamp.
- **`reference`** — a unique string, scoped to the function *and* callback. Creating another timer with the same reference **implicitly cancels the old one**. Pass `null` to have one generated; the call returns the reference either way.
- **`context`** — any serialisable JavaScript object, passed to the callback when the timer fires. Default maximum size **1024 bytes** (the Timer Context Max Size setting). For anything larger, store a document and pass its key.

`cancelTimer` returns a boolean; `false` typically means the timer never existed or had already fired. Cancelling a stale timer is a no-op, not an exception. Both functions throw if the underlying write to the Eventing Storage collection fails.

Operational facts that shape design:

- Timers inherit the parent function's execution timeout.
- A timer may fire on a **different node** than the one that created it.
- **One execution is guaranteed** despite node failures and rebalances. During a function backlog, timers fire eventually rather than on time.
- Timers are **deleted when the function is deleted or undeployed.** Pausing does not destroy them.
- Storage cost is roughly **832 + sizeof(context) bytes** per active timer, i.e. 832–1856 bytes at the default context size. Each timer is two KV documents plus a small root document shared by all timers due to fire in the same 7-second window, so each timer costs two or three inserts and two or three deletes regardless of whether it fires or is cancelled.
- Size the Eventing Storage collection for the peak number of active timers plus backlog.
- Timers require the cluster's clocks to be synchronised (NTP) at startup and periodically thereafter.
- A runtime or programmatic error in the callback can permanently block timer execution.

```javascript
function OnUpdate(doc, meta) {
    if (doc.type !== "session" || !doc.expires_at) return;
    var fireAt = new Date(doc.expires_at);
    if (fireAt <= new Date()) return;           // must be in the future
    createTimer(checkExpiry, fireAt, meta.id, { docId: meta.id });
}

function checkExpiry(context) {
    var d = src[context.docId];
    if (d && new Date() >= new Date(d.expires_at)) {
        delete src[context.docId];
    }
}
```

Source: [Timers](https://docs.couchbase.com/server/current/eventing/eventing-timers.html)

## SQL++ inside handlers

Write SQL++ **inline**, not through the `N1QL()` function. Eventing transpiles the handler source, recognises the SQL++ statement, and converts it into a call returning an iterable. The documentation states you **cannot use `N1QL()` directly, because it bypasses the transpiler's semantic and syntactic checks**. (`N1QL()` itself replaced the deprecated `N1qlQuery()`.)

```javascript
function OnUpdate(doc, meta) {
    if (doc.type !== "order") return;
    var customerId = doc.customer_id;                 // bind to a local first

    var results =
        SELECT SUM(o.total) AS total
        FROM `my-bucket`.orders.completed AS o
        WHERE o.customer_id = $customerId;            /* $ references the JS variable */

    for (var row of results) {
        var profile = profiles[customerId];
        if (profile) {
            profile.lifetime_value = row.total;
            profiles[customerId] = profile;
        }
        break;
    }
    results.close();                                  // always close
}
```

Rules that bite:

- **Always call `close()`** on the result set. It stops the underlying query and frees resources. Failing to close — especially with nested lookups — can exhaust query resources and degrade performance.
- Reference JavaScript variables with `$<variable>`. **You cannot use `meta.id` directly in a statement** — assign it to a local first (`var id = meta.id;` then `... WHERE username = $id`). `$meta.id` is invalid.
- Escape identifiers with backticks when they contain special characters: `` `beer-sample`._default._default ``. A plain name like `beersample` needs no escaping.
- In multiline statements, **do not use `//` end-of-line comments** before the terminating semicolon — it breaks the transpilation. Use `/* ... */`.
- The iterator is an input iterator: elements are read-only, its variables are local to it, and `this` is unusable inside its body.
- **SQL++ DML statements cannot manipulate documents in the bucket the function listens to.** This is the recursion guard. To write back to the source, use the bucket alias KV map instead.
- Consistency is controlled by the function's **SQL++ Consistency** setting (`n1ql_consistency`), valid values **None** (the default) and **Request**, and can be overridden per statement.

Every mutation that runs a query is a round trip to the Query Service. On a high-write source this saturates Query long before it saturates Eventing. Prefer a KV read through a bucket alias for single-document lookups.

Source: [Language Constructs](https://docs.couchbase.com/server/current/eventing/eventing-language-constructs.html)

## curl() for external HTTP calls

Enterprise Edition.

```javascript
response_object = curl(method, binding, request_object)
```

- **`method`** — a string: `GET`, `POST`, `PUT`, `HEAD`, or `DELETE`.
- **`binding`** — a **URL alias binding**, not a raw string. All calls through a binding are limited to descendants of its URL. Only `http://` and `https://` are supported.
- **`request_object`** keys:
  - **`headers`** — object of header name/value string pairs. *(This is the headers field — not `params`.)*
  - **`params`** — object of key/value pairs, URL-encoded and appended to the request URL as **query parameters**. Values must be string, number, or boolean.
  - **`path`** — appended to the binding's URL.
  - **`body`** — the request content.
  - **`encoding`** — `FORM`, `JSON`, `TEXT`, or `BINARY`. Omitted, it is inferred: a JS String becomes `text/plain`, a JS Object becomes `application/json`, a JS ArrayBuffer becomes `application/octet-stream`.
- **Return value** — an object with `body`, `status` (numeric HTTP status), and `headers`.
- **Errors** — an unexpected error throws a `CurlError`, which inherits from `Error`.

```javascript
function OnUpdate(doc, meta) {
    if (doc.status !== "shipped") return;

    var response = curl("POST", notificationService, {
        path: "/notify",
        headers: { "X-Request-Source": "eventing" },
        params: { orderId: meta.id },
        body: { orderId: meta.id, email: doc.customer_email }
    });

    if (response.status !== 200) {
        log("Notification failed for", meta.id, "status:", response.status);
    }
}
```

Security model: calls are confined to declared URL bindings, each carrying its own authentication (no auth, basic, bearer, digest), TLS setting, and certificate-validation setting. Client certificates are not currently supported. Cookie support is enabled per binding and should only be used against controlled, trusted endpoints. A URL binding should not target a node of the Couchbase cluster itself. Prefer `https://` whenever the binding carries credentials.

Timeouts: the handler's Script Timeout is the ceiling. From **8.0** you can set a per-request timeout in seconds on the `curl()` call, which takes precedence over the script timeout. A slow external call blocks mutation processing for that worker either way — for slow APIs, write a work-order document and process it out of band.

Source: [cURL](https://docs.couchbase.com/server/current/eventing/eventing-curl-spec.html)

## Logging

```javascript
log("Processing order", meta.id, "status:", doc.status);
```

`log()` writes to the function's own application log file (`<function_name>.log`), whose directory is set at node initialisation. The UI's **Log** view combines these across Eventing nodes. `log()` never throws. There is also a service-level `eventing.log` capturing management and lifecycle information, which functions cannot write to.

Viewing application logs requires **Full Admin** or **Eventing Full Admin**.

## What the JavaScript runtime does NOT support

Eventing uses Google V8, so most ECMAScript is available, but four capabilities are deliberately removed to allow automatic sharding and scaling:

- **Global state.** Global variables are not allowed, so that function logic is agnostic of rebalance. Persist state in the Data Service through bindings, or use a **Constant alias** for genuine constants.
- **Asynchrony.** No `setTimeout`, no promise-based flows, no sleeps or wake-ups. Handlers are short, straight-line code. Use **Timers** for deferred work.
- **Browser and other extensions.** No `window`, no DOM, no `XMLHttpRequest`. Use `curl()` instead.
- **Library imports.** You cannot import libraries into a function.

## Error handling patterns

**Transient errors.** Catch, log, and decide: re-throwing means the mutation is retried; swallowing means it is skipped.

```javascript
function OnUpdate(doc, meta) {
    try {
        // operation that may fail transiently
    } catch (e) {
        log("Error processing", meta.id, ":", e.message);
        // re-throw to retry; return to skip
    }
}
```

**Permanent errors.** Guard at the top of the handler and return early, so bad documents do not repeatedly fail.

```javascript
function OnUpdate(doc, meta) {
    if (!doc.type || doc.type !== "order") return;
    if (!doc.customer_id) { log("Missing customer_id on", meta.id); return; }
    // process
}
```

## Handler performance

- **Return early.** A type check on the first line is the single biggest lever, because it costs nothing for the documents you do not care about.
- **Prefer bucket-alias KV reads over SQL++** for single-document lookups.
- **Close every SQL++ result set.**
- **Design for one-at-a-time processing.** Each worker handles one mutation at a time; there is no batch API. Accumulate work orders and process them separately if you need batching.
- **Treat Script Timeout as a ceiling, not a target.** The default is 60 seconds; a handler anywhere near that is a design problem, not a tuning problem.

## Mutation deduplication — what your handler actually sees

The KV data engine deduplicates multiple mutations to a single document made in quick succession before they reach DCP. Because Eventing consumes DCP, handlers see only the deduplicated events. Consequences to design around:

- You **cannot distinguish a create from an update** in `OnUpdate` — both arrive as the same event.
- You **cannot get the old value** of a document inside a handler; there is no built-in versioning. If you need change history, write it into the document or a side collection as part of your own logic.
- Your handler is guaranteed the document's *final* state, but may never observe intermediate states of a rapidly changing document. Reconcile against final state; do not build state machines that assume every transition is observed.
- A write performed by a handler is itself a mutation that can be seen by that handler or another one. In bidirectional XDCR topologies this can become a cross-cluster loop — add guards.

## Built-in functions

The documented built-ins are:

- `N1QL()` — present, but **do not call it directly**; write SQL++ inline.
- `couchbase.analyticsQuery()`
- `crc64()` and `crc_64_go_iso()`
- Base64 functions — `couchbase.base64Encode` / `base64Decode` for arbitrary JSON, and the typed array helpers `couchbase.base64Float32ArrayEncode` / `Decode` and `couchbase.base64Float64ArrayEncode` / `Decode`, which pack a float array into a base64 string and back. These are the supported way to move embedding vectors through text-based paths without hand-rolling encoding.
- `createTimer()` and `cancelTimer()`
- `curl()`

## Eventing and Capella's Vectorization Service

Capella AI Services Workflows create dedicated metadata collections and **Eventing functions** on the chosen Capella operational cluster — two Eventing functions per Workflow. So Eventing capacity and the Eventing Storage keyspace are part of the sizing picture for a vectorization workload, and those generated functions will appear alongside your own on the Eventing page.

Batching behaviour and the embedding model's maximum input length are properties of the Workflow and the chosen model, not documented Eventing parameters. Do not quote a batch size; read the model's own limits and the Workflow configuration. ([Process Your Data For Capella AI Services](https://docs.couchbase.com/ai/build/vectorization-service/data-processing.html))

When writing embedding vectors yourself, use the `couchbase.base64Float32ArrayEncode` / `Decode` and `couchbase.base64Float64ArrayEncode` / `Decode` helpers above rather than hand-rolling encoding, so float arrays survive text-based paths intact.
