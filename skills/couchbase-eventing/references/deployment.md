# Eventing deployment

## Contents

- [The four things you choose when adding a function](#the-four-things-you-choose-when-adding-a-function)
- [Function Scope](#function-scope)
- [Listen To Location](#listen-to-location)
- [Eventing Storage (metadata keyspace)](#eventing-storage-metadata-keyspace)
- [Feed Boundary](#feed-boundary)
- [Settings and their defaults](#settings-and-their-defaults)
- [Bindings](#bindings)
- [The exported function definition](#the-exported-function-definition)
- [Updating a function without losing the checkpoint](#updating-a-function-without-losing-the-checkpoint)
- [RBAC](#rbac)

## The four things you choose when adding a function

In the ADD FUNCTION dialog: **Function Scope**, **Listen To Location**, **Eventing Storage**, and **Function Name** (unique across the cluster), plus the **Deployment Feed Boundary**, an optional description, the settings panel, and bindings.

Source: [The Eventing Lifecycle](https://docs.couchbase.com/server/current/eventing/eventing-lifecycle.html)

## Function Scope

A `bucket.scope` pair used as an RBAC grouping that identifies functions belonging together.

- Set it to the `bucket.scope` that contains the collection your function listens to. This keeps the function's scope pointed at a resource it actually needs, so the function is not undeployed by the removal of an unrelated scope.
- Setting Function Scope to `*.*` requires **Eventing Full Admin** or **Full Admin**. Other users must reference an existing `bucket.scope` they have rights on.

## Listen To Location

The source keyspace: `bucket.scope.collection`. From **7.1.1**, a function can listen to multiple collections by using `*` for the scope and/or collection.

If the Listen To Location uses a wildcard, and a bucket alias in the function also uses a wildcard, the handler must use **Advanced Keyspace Accessors** rather than the simple map syntax.

## Eventing Storage (metadata keyspace)

A collection used solely by the Eventing Service, holding DCP stream checkpoints, timer state, and internal function documents.

Rules:

- **Never write or delete application data in it from a handler.**
- **Never make it the Listen To Location of another function.**
- Do not delete or flush it, and do not update its keys externally.
- It should be **effectively 100% resident** — size the bucket so the collection stays in memory.
- A common Eventing Storage collection **can** be shared across all Eventing functions for the same tenant. Splitting it by logical grouping or tenant is a reasonable choice; a separate collection per function is not required. (The `user_prefix` setting namespaces a function's documents within a shared collection.)
- If you use timers, size it for the peak number of active timers plus any backlog. Each active timer costs roughly 832 bytes plus the context size (default context limit 1024 bytes).

The lifecycle walkthrough in the documentation uses a small dedicated bucket (100 MiB) with an `eventing` scope and a `metadata` collection, which is a sensible shape for a first deployment.

## Feed Boundary

- **Everything** — the function processes all mutations available in the cluster from the Listen To Location, including existing documents.
- **From now** — only mutations after deployment.

It is a **persistent setting in the function definition**, and it can only be set or altered when the function is **created, undeployed, or paused**. It is not an argument to the deploy call. In the exported/REST form it is `dcp_stream_boundary`, valued `everything` or `from_now`.

Pick **From now** when the function is an additive pipeline that does not need to backfill history, and **Everything** when derived state must be built for documents that already exist. Deploying with **Everything** against a large existing collection can take a long time and will generate derived documents from old data — a common cause of "unexpected documents appeared".

## Settings and their defaults

From the Add Function dialog and [Eventing Terminology](https://docs.couchbase.com/server/current/eventing/eventing-Terminologies.html):

| Setting (UI) | Definition key | Default | Notes |
|---|---|---|---|
| Workers | `worker_count` | **1** | Minimum 1; recommended maximum 64. Raise when the DCP backlog grows and handler time is already short |
| Script Timeout | `execution_timeout` | 60 s | Per-invocation ceiling for `OnUpdate`, `OnDelete`, and timer callbacks |
| OnDeploy Timeout | — | 60 s | 8.0+. Exceeding it reverts the function to its previous state |
| SQL++ Consistency | `n1ql_consistency` | `None` | Valid values `None` and `Request`; can be overridden per statement |
| Language compatibility | `language_compatibility` | `6.6.2` | **Only `6.0.0`, `6.5.0`, and `6.6.2` are defined.** It pins runtime semantics to the behaviour at authoring time |
| Timer Context Max Size | `timer_context_size` | 1024 bytes | Per-function |
| System Log Level | `log_level` | `INFO` | Info, Error, Debug, Warning, Trace. Leave alone unless Support asks |
| Application log location | — | node setting | Set at node initialisation; the UI combines these across nodes |
| Deployment / processing state | `deployment_status`, `processing_status` | `false` | `deployment_status:false` = undeployed; `processing_status:false` on a deployed function = paused |
| Metadata namespace | `user_prefix` | `eventing` | Namespaces a function's documents inside a shared Eventing Storage collection |
| Nodes to run on | `num_nodes_running` | all nodes | **8.0+**. Set at function scope config level; if fewer nodes are available the function runs on all of them |

On worker count: each worker holds memory and CPU on every Eventing node the function runs on, so the cluster-wide worker total is `worker_count` times the number of participating Eventing nodes. Increase in small steps and watch Eventing memory as well as backlog.

**8.0** also allows configuration such as `enable_curl` and `enable_debugger` to be set at bucket or scope level rather than only per function.

## Bindings

Declared in the function configuration and available as globals in the handler:

- **Bucket alias** — alias name, keyspace (`bucket.scope.collection`, wildcards allowed), and access level **read only** or **read and write** (`"r"` / `"rw"` in the exported definition). At least one bucket alias is required for the function to touch the Data Service.
- **URL alias** — alias name, URL, cookie setting, SSL certificate validation setting, and authorization type (no auth, basic, bearer, digest). Client certificates are not supported. The target should not be a Couchbase cluster node.
- **Constant alias** — alias name and a value (integer, decimal, string, boolean, or JSON object), behaving as a `const` declaration.

Grant read-only wherever a function only reads. Bucket aliases are the function's entire Data Service authority, so an overly broad `rw` alias on a production keyspace is a real risk.

## The exported function definition

Functions can be exported and imported as JSON, which is the practical way to promote a function from test to production. A minimal shape:

```json
{
  "appname": "my-function",
  "appcode": "function OnUpdate(doc, meta) { ... }",
  "depcfg": {
    "source_bucket": "my-bucket",
    "source_scope": "my-scope",
    "source_collection": "orders",
    "metadata_bucket": "rr100",
    "metadata_scope": "eventing",
    "metadata_collection": "metadata",
    "buckets": [
      {
        "alias": "processed",
        "bucket_name": "my-bucket",
        "scope_name": "my-scope",
        "collection_name": "processed-orders",
        "access": "rw"
      }
    ],
    "curl": [ { "value": "notificationService", "hostname": "https://api.internal.example", "auth_type": "bearer", "allow_cookies": false, "validate_ssl_certificate": true } ]
  },
  "settings": {
    "deployment_status": false,
    "processing_status": false,
    "dcp_stream_boundary": "everything",
    "worker_count": 1,
    "execution_timeout": 60,
    "timer_context_size": 1024,
    "log_level": "INFO",
    "language_compatibility": "6.6.2",
    "n1ql_consistency": "none",
    "user_prefix": "eventing"
  }
}
```

Do not hand-edit an exported file before reimporting it — the documentation explicitly warns against this, and the internal format of the function body is not a stable, standardised interface. Treat export/import as a whole-object operation.

Source: [Exporting Functions](https://docs.couchbase.com/server/current/eventing/eventing-function-export.html)

## Updating a function without losing the checkpoint

1. **Pause** the function — processing stops, the DCP checkpoint is held.
2. **Edit the JavaScript or settings.** Editing is only permitted while Paused or Undeployed.
3. **Resume** — processing continues from the paused checkpoint.

Undeploying instead discards the checkpoint, so the next deploy replays according to the Feed Boundary — with **Everything**, that means the entire source collection again. Undeploying also **deletes all pending timers**.

Feed Boundary itself can only be changed while the function is created, undeployed, or paused.

## RBAC

- **Full Admin** and **Eventing Full Admin** can manage all Eventing functions, can set Function Scope to `*.*`, and can read any function's application log. Every other user needs a Function Scope that references an existing `bucket.scope` they hold rights on, and the corresponding privileges on the keyspaces involved.
- The function's data access is bounded by its **bucket alias bindings** and their access levels — grant read-only where possible.
- A function that runs SQL++ needs the relevant Query privileges on the keyspaces it queries.
- See [Eventing Role-Based Access Control](https://docs.couchbase.com/server/current/eventing/eventing-rbac.html) for the non-privileged-user setup.
