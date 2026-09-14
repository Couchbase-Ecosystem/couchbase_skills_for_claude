# Safety — read-only by default, and how to handle a write

The official Couchbase MCP server ships safe: writes are off until someone turns them on. This reference covers the mechanisms that enforce that, the operations they cover, and how to handle a request that needs a write.

## Contents

- [The posture](#the-posture)
- [Mechanism 1 — read-only mode](#mechanism-1--read-only-mode)
- [Mechanism 2 — disabled tools](#mechanism-2--disabled-tools)
- [Mechanism 3 — confirmation via elicitation](#mechanism-3--confirmation-via-elicitation)
- [RBAC is the real boundary](#rbac-is-the-real-boundary)
- [Taxonomy of write operations](#taxonomy-of-write-operations)
- [What is safe to call freely](#what-is-safe-to-call-freely)
- [Handling a write request](#handling-a-write-request)
- [Dialog patterns](#dialog-patterns)
- [Decision tree](#decision-tree)

## The posture

**Treat the cluster as read-only.** Reads need no ceremony. Anything that writes, drops, or deletes needs the user's explicit approval, obtained immediately before the call, describing the specific target and the blast radius.

This holds regardless of how the server is configured. The presence of a write tool is not permission to use it — it only means someone turned writes on for the session. Approval is a separate thing, and it is granted per operation, not once per conversation.

Three things follow:

1. Never treat an earlier "yes, go ahead" as covering a later, different write.
2. Never treat a general instruction ("clean up the test data") as approval for the specific deletes you decided that meant. Name them and confirm.
3. Never work around a missing tool. If a write tool is absent, that is the configuration functioning correctly.

## Mechanism 1 — read-only mode

`CB_MCP_READ_ONLY_MODE` defaults to **`true`**. It is the single switch controlling writes, and it acts in two places.

**Write tools are not loaded.** All 12 of them are simply absent from tool discovery — not hidden, not erroring, absent:

- KV: `upsert_document_by_id`, `insert_document_by_id`, `replace_document_by_id`, `delete_document_by_id`, `mutate_subdocument`
- Scope/collection: `create_scope`, `create_collection`, `delete_scope`, `delete_collection`
- Index: `create_index`, `build_index`, `drop_index`

The 25 read-only tools remain available.

**SQL++ is guarded at runtime.** `run_sql_plus_plus_query` still exists, but it parses each statement and refuses anything that is not purely read-only. The guard is deny-by-default: a statement passes only if every top-level statement is in the read-only allow-list (SELECT, INFER, ADVISE and similar). Refusals are labelled:

| Label | Meaning |
|---|---|
| `data` | DML — INSERT, UPDATE, DELETE, UPSERT, MERGE |
| `structure` | DDL — CREATE / DROP / ALTER of indexes, scopes, collections |
| `privilege` | DCL — GRANT, REVOKE |
| `write` | Any other non-read statement class |

Because the allow-list decides rather than a list of forbidden forms, new statement classes are blocked by default. Do not try to phrase around it.

**You cannot change this from the client.** It lives in the server's environment and takes a restart. When a user needs a write that read-only mode blocks, state that plainly and let them choose: enable writes deliberately in the server's environment, or do the operation in the Couchbase Web Console. Do not present flipping the flag as a quick fix, and never recommend disabling it permanently for convenience.

## Mechanism 2 — disabled tools

`CB_MCP_DISABLED_TOOLS` removes named tools from discovery entirely, independently of read-only mode. It takes a comma-separated list or a path to a file with one tool name per line (`#` comments allowed).

A disabled tool is invisible and uninvokable. If a tool you expected is missing and read-only mode does not explain it, this is the likely reason — check `get_server_configuration_status`, which reports the disabled list without connecting to the cluster.

Disabling is a guardrail for model behaviour, not a security control. See [RBAC is the real boundary](#rbac-is-the-real-boundary).

## Mechanism 3 — confirmation via elicitation

`CB_MCP_CONFIRMATION_REQUIRED_TOOLS` names tools that must be confirmed by the user before they run. Same two formats as the disabled list.

When a listed tool is invoked and the MCP client supports elicitation, the user is prompted. **If the client does not support elicitation, the tool runs without confirmation** — for backward compatibility. That caveat matters: this mechanism cannot be relied on as the only gate, because whether it fires depends on the client. Your own explicit confirmation step is the one that is always present.

A reasonable list for an agent-driven deployment with writes enabled: `delete_document_by_id`, `delete_scope`, `delete_collection`, `drop_index`, `replace_document_by_id`.

## RBAC is the real boundary

The Couchbase user in `CB_USERNAME` (or the mTLS certificate identity) determines what is actually possible. Everything above shapes what the model is offered; RBAC decides what the cluster permits.

The concrete consequence, from the server's own documentation: disabling `upsert_document_by_id` and `delete_document_by_id` does **not** prevent data modification, because `run_sql_plus_plus_query` can issue DML — unless `CB_MCP_READ_ONLY_MODE` is true, or the database user lacks the RBAC permissions to modify data.

So: give the MCP user the narrowest roles that let it do its job, and treat tool gating as a second layer that reduces surface area and guides behaviour. Role guidance is in `security-best-practices.md`.

## Taxonomy of write operations

### Irreversible — data loss without a backup

| Operation | Impact |
|---|---|
| `delete_document_by_id` | One document, gone |
| `delete_collection` | The collection **and every document in it** |
| `delete_scope` | The scope **and every collection in it**, recursively |

`delete_scope` is the sharpest edge in this server. Its blast radius is usually much larger than the user pictures — always enumerate the collections it will take with it (`get_scopes_and_collections_in_bucket`) and name them back before proceeding.

### Destructive in place

| Operation | Impact |
|---|---|
| `mutate_subdocument` | Overwrites or removes named paths inside an existing document. `remove_paths` deletes data outright, and there is no prior version to fall back on. All-or-nothing per call |
| `replace_document_by_id` | Overwrites the whole document. The previous content is gone |
| `upsert_document_by_id` | Same, and additionally creates the document if absent — so a typo in the ID silently creates a new document instead of failing |

`insert_document_by_id` is the safest whole-document write: it fails rather than overwriting.

### Recoverable but expensive

| Operation | Impact |
|---|---|
| `drop_index` | The definition is recoverable if recorded, but rebuilding a large index can take a long time, and queries depending on it degrade to primary scans meanwhile. Capture the `definition` from `list_indexes` before dropping |
| `create_index` / `build_index` | Not destructive, but a build consumes Index Service resources and adds write amplification on every subsequent mutation to the collection. On a large collection the build is a real operational event, not a free action |

### Structure creation

`create_scope` and `create_collection` are low-risk, but they change the shape of the data model and may conflict with an application's expectations or an IaC definition. Confirm naming with the user rather than inventing it.

## What is safe to call freely

All 25 read-only tools. No confirmation needed:

- `get_server_configuration_status`, `test_cluster_connection`, `get_cluster_health_and_services`, `get_cluster_diagnostics_report`
- `get_buckets_in_cluster`, `get_scopes_in_bucket`, `get_collections_in_scope`, `get_scopes_and_collections_in_bucket`, `get_schema_for_collection`
- `get_document_by_id`, `lookup_subdocument`
- `run_sql_plus_plus_query` for SELECT-class statements, `explain_sql_plus_plus_query`
- `list_indexes`, `get_index_advisor_recommendations`
- `list_fts_indexes`, `get_fts_index_definition`, `run_fts_query`
- All seven `get_queries_*` performance tools

Two carry a cost worth noting even though they change nothing:

- **`get_cluster_health_and_services`** actively pings every targeted service — a real network round-trip. Narrow it with `service_types`, or prefer `get_cluster_diagnostics_report`, which performs no I/O at all.
- **`run_fts_query` with `explain=true`** still executes the query; the Search Service exposes the plan per matched hit rather than as a dry run. `limit` defaults to 1 in that mode to keep it cheap.

And one boundary case: an unbounded `run_sql_plus_plus_query` is read-only but can return an enormous result set and load the Query Service. Add a `LIMIT` when exploring.

## Handling a write request

1. **Establish the exact target.** Bucket, scope, collection, document ID, index name. Resolve ambiguity with a read first — `get_document_by_id` before deleting it, `list_indexes` before dropping one, `get_scopes_and_collections_in_bucket` before dropping a scope.
2. **State the impact in concrete terms.** What changes, what is lost, whether it is reversible, and what recovery would require. "This deletes the `staging` scope and the 4 collections in it: `users`, `orders`, `events`, `sessions`. All documents in them are gone; recovery requires a backup."
3. **Ask for unambiguous confirmation.** Not "shall I proceed?" — have the user name the thing: "reply `delete staging scope` to confirm."
4. **Call once, with exactly the confirmed arguments.** Do not broaden the scope of the operation between confirmation and call.
5. **Report the result verbatim.** If it failed, surface the error rather than retrying with different arguments.

Skipping steps 2 and 3 because the user "already said delete it" is the single most common route to an incident.

## Dialog patterns

**Deleting a document**

> **User:** Delete user_4711 from the users collection.
>
> **You:** *(reads it first with `get_document_by_id`)* `user_4711` in `app.main.users` is the account for alice@example.com, created 2024-03-02. Deleting it is permanent — there is no undo without a backup. Reply `delete user_4711` to confirm.
>
> **User:** delete user_4711
>
> **You:** *(calls `delete_document_by_id` with exactly that keyspace and ID)* Deleted.

**Dropping a scope**

> **User:** Get rid of the old staging scope.
>
> **You:** *(calls `get_scopes_and_collections_in_bucket`)* `staging` in the `app` bucket contains 4 collections: `users`, `orders`, `events`, `sessions`. `delete_scope` removes the scope and all four, with every document in them. This is permanent; recovery requires a backup. Confirm you want all four gone by replying `delete staging scope`.

**Write tool absent**

> **User:** Update that document's status to `archived`.
>
> **You:** The MCP server is running in read-only mode (`CB_MCP_READ_ONLY_MODE=true`, the default), so the write tools are not loaded and a SQL++ UPDATE would be blocked. Two options: enable writes deliberately in the server's environment and restart it, or make this change in the Couchbase Web Console. I can show you the document as it stands now if that helps.

**Creating an index**

> **User:** The advisor suggested an index on `email` — create it.
>
> **You:** That index will be maintained on every mutation to `app.main.users`, and the initial build on a collection this size will take time and Index Service resources. `list_indexes` shows an existing `idx_users_type` on `type` — widening that may serve both queries instead of adding a second index. Do you want the new index as suggested, or should I look at extending the existing one? If the new one: I will create it deferred, then build it, then confirm it reaches `online`.

## Decision tree

- **Read-only tool?** → call it.
- **`run_sql_plus_plus_query` with a SELECT?** → call it; add a `LIMIT` when exploring.
- **Any write, DDL, or delete?** → identify the exact target, state the impact, get explicit confirmation naming the target, then call once.
- **Write tool missing?** → read-only mode or a disabled-tools list. Check `get_server_configuration_status`, report it, offer the Web Console. Do not work around it.
- **Dropping a scope or collection?** → enumerate the contents first and name them back.
- **Dropping an index?** → capture its `definition` from `list_indexes` first, so it can be recreated.
- **User says "just do it" without a specific target?** → resolve the target with a read, then confirm. Ambiguity is not consent.
