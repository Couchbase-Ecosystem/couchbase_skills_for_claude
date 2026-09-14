# Troubleshooting

Symptom-first guide to things going wrong with the official Couchbase MCP server. Each section starts with what the user sees, then likely causes in rough order of frequency, then how to confirm.

## Contents

- [First three checks](#first-three-checks)
- [The server will not start](#the-server-will-not-start)
- [Tools are missing](#tools-are-missing)
- [Connection failures](#connection-failures)
- [Authentication and permission failures](#authentication-and-permission-failures)
- [SQL++ query problems](#sql-query-problems)
- [Index problems](#index-problems)
- [Search (FTS) problems](#search-fts-problems)
- [Key-value and sub-document problems](#key-value-and-sub-document-problems)
- [Performance tools return nothing](#performance-tools-return-nothing)
- [Gathering information for a bug report](#gathering-information-for-a-bug-report)
- [Decision tree](#decision-tree)

## First three checks

Before diagnosing anything specific, in this order — each is cheap and each rules out a whole class of problem:

1. **`get_server_configuration_status`** — does not connect to the cluster. Tells you read-only mode, disabled tools, confirmation-required tools, OAuth settings and logging. Answers "is the server configured the way I think?"
2. **`get_cluster_diagnostics_report`** — no network I/O. Shows the SDK's cached view of every endpoint and an overall online/degraded/offline state.
3. **`test_cluster_connection`** — actually connects with the configured credentials. Optionally pass `bucket_name` to check one bucket.

If step 1 works and step 3 fails, the problem is connectivity or credentials, not configuration. If step 1 itself cannot run, the server is not up — see below.

## The server will not start

**Symptom: the client shows the server as failed, stopped, or with zero tools.**

1. **`uvx` not on the client's PATH.** GUI applications launched outside a shell often have a minimal PATH. Put the absolute path to `uvx` in the `command` field.
2. **A config using `npx`.** There is no Node distribution of this server. It is Python, via PyPI or Docker. Replace `npx` with `uvx couchbase-mcp-server`.
3. **Python below 3.10.** The server requires 3.10 or higher.
4. **Wrong top-level JSON key.** VS Code uses `servers`; Claude Desktop, Cursor and Windsurf use `mcpServers`. The wrong key means the entry is silently ignored.
5. **Partial OAuth configuration.** OAuth activates only when `CB_MCP_OAUTH_JWT_JWKS_URI`, `CB_MCP_OAUTH_JWT_ISSUER` and `CB_MCP_OAUTH_JWT_AUDIENCE` are all set. Setting some but not all **fails at startup** by design.
6. **Running from source after a pull.** Dependencies drift — run `uv sync` in the repository.
7. **Invalid JSON in the client config.** A trailing comma is enough.

Where to find the logs: Claude Desktop in `~/Library/Logs/Claude` (macOS) or `%APPDATA%\Claude\Logs` (Windows); Cursor under Output → Cursor MCP; VS Code via **MCP: List Servers** → the server → Show Output; JetBrains under Help → Show Log in Finder/Explorer → `mcp/couchbase`.

## Tools are missing

**Symptom: an expected tool does not appear in the tool list.**

This is almost always deliberate configuration, in this order:

1. **Read-only mode.** `CB_MCP_READ_ONLY_MODE` defaults to `true`, and all 12 write tools are then **not loaded**: the five KV writes, the four scope/collection tools, and the three index tools. This is the correct behaviour, not a fault.
2. **`CB_MCP_DISABLED_TOOLS`.** Named tools are removed from discovery entirely.
3. **OAuth scopes.** On HTTP transport with OAuth, a token without `couchbase-mcp:write` does not get the write tools.
4. **The tool does not exist.** Check `tool-index.md`. There are no cluster-administration or Capella control-plane tools in this server — never invent one.

`get_server_configuration_status` reports the first two directly. Report what you find rather than working around it; see `safety.md`.

## Connection failures

**Symptom: cannot connect, connection refused, timeout.**

1. **Wrong connection string scheme.** `couchbases://` for TLS — always for Capella. `couchbase://` is plaintext. Mixing these up is the most common cause.
2. **Capella IP allowlist.** The machine running the MCP server must be allowed in the Capella cluster's allowed IP list. Note that it is the **server's** address that matters, not the user's laptop, when the server runs elsewhere.
3. **Untrusted server certificate.** A self-signed or private-CA cluster certificate needs `CB_CA_CERT_PATH`. Do not look for a way to skip verification.
4. **Firewall blocking data ports.** The management port may answer while KV or Query ports are blocked, which looks like "connects but nothing works". `get_cluster_health_and_services` with `service_types` narrows down which service is unreachable.
5. **Docker networking.** From a container, a cluster on the host is usually `couchbase://host.docker.internal`, not `localhost`.
6. **The cluster is genuinely down or rebalancing.**

Diagnostic order: `get_cluster_diagnostics_report` (free, cached state) → `test_cluster_connection` (real connection) → `get_cluster_health_and_services` with a narrow `service_types` (live per-service ping).

**Symptom: connects, then drops after idle.** Idle connections reaped by a NAT, load balancer or firewall. This is SDK and network configuration outside the MCP server's settings; `get_cluster_diagnostics_report`'s `last_activity` per endpoint confirms the pattern.

## Authentication and permission failures

**Symptom: unauthorized, 401, authentication failure.**

1. **Wrong username or password** in `CB_USERNAME` / `CB_PASSWORD`.
2. **A Capella API key used as database credentials.** They are different things. The MCP server needs a **database user** created on the cluster; a Capella API key authenticates to the Capella Management API and will not work here.
3. **mTLS misconfiguration.** If `CB_CLIENT_CERT_PATH` and `CB_CLIENT_KEY_PATH` are set, they take precedence over username and password — so a stale certificate silently wins over correct credentials. Check whether both forms are configured.
4. **Certificate path wrong or unreadable** by the process.

**Symptom: connects, but forbidden on a specific operation.**

The user exists but lacks the role. Common shapes:

- No `query_select` on the bucket → SQL++ fails while KV reads work
- No `fts_searcher` → Search tools fail while everything else works
- No monitoring privilege → the `get_queries_*` performance tools fail or return nothing
- No `query_manage_index` → `create_index` / `drop_index` fail even with writes enabled
- Access to no bucket at all → `get_buckets_in_cluster` returns an empty list

An empty bucket list from a working connection is the signature of a user with no bucket grants. Roles are managed on the cluster, not here: Couchbase Web Console, `couchbase-cli`, or the Management REST API (Capella: the Capella UI or Management API v4). See `security-best-practices.md` for which roles a deployment needs.

## SQL++ query problems

**Symptom: the query is blocked, not executed.**

Read-only mode's write guard. The refusal is labelled `data` (DML), `structure` (DDL), `privilege` (DCL) or `write`. Expected behaviour — see `safety.md`. Do not rephrase to evade it.

**Symptom: keyspace not found, or a name resolution error.**

Almost always double-qualification. `run_sql_plus_plus_query` already sets the query context to the given bucket and scope, so collection names must be bare:

```sql
SELECT * FROM airline WHERE country = $country          -- correct
SELECT * FROM `travel-sample`.inventory.airline ...     -- wrong in this tool
```

Otherwise: confirm the keyspace actually exists with `get_scopes_and_collections_in_bucket`, and remember names are case-sensitive.

**Symptom: syntax error.**

- Identifiers containing hyphens or reserved words need backticks: `` `travel-sample` ``
- Array predicates use `ANY x IN arr SATISFIES x.field = "v" END`
- SQL++ has no native DATE type — use the millisecond/string conversion functions

`explain_sql_plus_plus_query` surfaces parse errors without executing anything.

**Symptom: the query runs but returns unexpected or stale results.**

GSI indexes are eventually consistent by default, so a read immediately after a write may not see it. Confirm by fetching the document directly with `get_document_by_id` — KV reads are immediately consistent. Query consistency levels are set through SDK query options; where this tool does not expose them, KV is the reliable read-after-write path.

**Symptom: the query hangs or returns an enormous result.**

An unbounded `SELECT` on a large collection. Add a `LIMIT` when exploring, always.

## Index problems

**Symptom: an index was created but queries do not use it.**

`create_index` defaults to `deferred=True` — the index is defined but **not built**. Call `build_index` on the collection, then `list_indexes` to confirm the status reaches `online`. An index that is not online cannot serve a query.

**Symptom: an index is missing from `list_indexes`.**

On **8.0+**, `list_indexes` reads `system:indexes` through the Query Service and is RBAC-scoped — the connected user sees only indexes on keyspaces they can access. On **7.x** it uses the admin-level Index Service REST API. A narrow user therefore sees a narrower listing on 8.0+. Check the user's roles before concluding the index does not exist.

Also check the filters: they are hierarchical, so `scope_name` requires `bucket_name` and `collection_name` requires both.

**Symptom: entries carry a warning instead of the expected fields.**

When a required field is absent from the source row, the entry returns a warning plus `raw_index_stats`. Set `return_raw_index_stats=true` to see the unprocessed data.

**Symptom: `create_index` fails with an existing-index error.**

The name is taken. Either choose another name or pass `ignore_if_exists=true`. Check `list_indexes` first — an existing index of nearly the right shape is usually better widened than duplicated.

## Search (FTS) problems

**Symptom: the FTS tools are absent or fail outright.**

They require Couchbase Server **7.6+ and the Search Service** running on the cluster. Confirm the service is present with `get_cluster_health_and_services` using `service_types: ["search"]`.

**Symptom: `list_fts_indexes` returns nothing.**

Filtering follows the two index models and it is easy to look in the wrong one. With no filters you get **cluster-level (legacy) indexes only**. Scope-level indexes need `bucket_name` (all scopes in the bucket) or `bucket_name` + `scope_name` (one scope). `scope_name` alone is invalid and returns an error.

**Symptom: `get_fts_index_definition` rejects the arguments.**

Pass **both** `bucket_name` and `scope_name` for a scoped index, or **neither** for a cluster-level one. One without the other is invalid. Use the `bucket`/`scope` values from that index's own `list_fts_indexes` entry — they are `null` for cluster-level indexes — rather than reusing the filter you listed with.

**Symptom: a query matches nothing but the data is definitely there.**

A field-scoped query against a field the index does not map matches nothing rather than erroring. Call `get_fts_index_definition` and check what is actually mapped and how it is analyzed before assuming the data is wrong.

**Symptom: `explain=true` seems to have run the query.**

It did. The Search Service exposes the plan per matched hit, not as a separate dry run, so explain mode executes the query with explanation enabled. `limit` defaults to 1 in that mode to keep it cheap.

## Key-value and sub-document problems

**Symptom: `get_document_by_id` raises instead of returning empty.** By design — a missing document is an exception, not an empty result. Check the ID and the keyspace.

**Symptom: a sub-document path returns a per-path error.** The path does not exist in that document, or is the wrong type for the operation (`count_paths` needs an array or object). Do not guess paths: fetch the document with `get_document_by_id`, or the shape with `get_schema_for_collection`, then address real paths.

**Symptom: `mutate_subdocument` fails and nothing was applied.** It is all-or-nothing. One failing spec — an `insert` on an existing path, a counter on a non-numeric field — fails the whole call. Split the batch, or fix the offending spec.

**Symptom: `mutate_subdocument` says the document does not exist.** It only modifies existing documents. Create it with `upsert_document_by_id` first (a write, so confirm it).

**Symptom: `insert_document_by_id` fails with a duplicate.** Working as intended. Use `upsert_document_by_id` if overwriting is genuinely wanted — and confirm, since that discards the existing content.

## Performance tools return nothing

The `get_queries_*` tools read the Query Service's record of completed requests. An empty result means one of:

- **Nothing crossed the logging threshold.** Trivial sub-second queries often never appear. An empty list is not proof of a healthy workload.
- **The user lacks the privilege** to read those statistics — typically a cluster-level monitoring role.
- **The cluster genuinely has little query traffic**, for example a KV-only workload.

Confirm the third by checking whether the Query Service is running at all: `get_cluster_health_and_services` with `service_types: ["query"]`.

## Gathering information for a bug report

Issues go to https://github.com/couchbase/mcp-server-couchbase/issues — the project is Couchbase community-maintained, and the support portal does not handle it.

Collect:

- `uvx couchbase-mcp-server --version`
- The output of `get_server_configuration_status` (already redacted of secrets)
- Debug logs: `--log-level=debug --log-sinks=stderr,file`
- With the `file` sink on, `mcp_server_config.log.json` — a one-shot snapshot of OS, Python, dependency versions, transport, resolved logging and redacted server config, rewritten at each start
- Couchbase Server version and edition, and whether it is Capella or self-managed
- The exact tool call and the exact error

Check every artifact for credentials before sharing it.

## Decision tree

- **No tools at all** → the server is not running. Check PATH, `npx`-vs-`uvx`, Python version, JSON validity, client logs.
- **Some tools missing** → read-only mode, `CB_MCP_DISABLED_TOOLS`, or OAuth scopes. Confirm with `get_server_configuration_status`.
- **Cannot connect** → scheme, Capella IP allowlist, CA certificate, firewall. `get_cluster_diagnostics_report` → `test_cluster_connection`.
- **Connects, unauthorized** → wrong credentials, or a Capella API key used where a database user is needed.
- **Connects, forbidden on one thing** → missing RBAC role. Fix on the cluster, not here.
- **Empty bucket list** → the user has no bucket grants.
- **SQL++ blocked** → read-only mode write guard, working correctly.
- **Keyspace not found** → double-qualified collection name inside an already-scoped query.
- **Index not used** → it was created deferred and never built. `build_index`, then confirm `online`.
- **Index not listed on 8.0+** → RBAC-scoped listing; check the user's roles.
- **FTS matches nothing** → check the index definition for what is actually mapped.
- **FTS index not listed** → wrong filter for cluster-level vs scope-level.
- **Performance tools empty** → nothing logged, no monitoring privilege, or no query traffic.
