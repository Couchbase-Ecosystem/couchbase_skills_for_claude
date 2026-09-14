# Safety and trust model

How the Couchbase Admin MCP server decides whether a mutating call is allowed to
happen, and what an operator or agent has to do to get past each control. Every
statement here is drawn from the server's README and dispatch code; where the
source is silent, this file says so rather than guessing.

## Contents

- [The shape of it](#the-shape-of-it)
- [Layer 1 — read-only mode](#layer-1--read-only-mode)
- [Layer 1a — dry run](#layer-1a--dry-run)
- [Layer 2 — confirmation, and the two ways to satisfy it](#layer-2--confirmation-and-the-two-ways-to-satisfy-it)
- [Layer 3 — the hard ceiling](#layer-3--the-hard-ceiling)
- [Order of evaluation](#order-of-evaluation)
- [Per-environment policy](#per-environment-policy)
- [Capella guardrails — a separate, parallel control](#capella-guardrails--a-separate-parallel-control)
- [Audit](#audit)
- [What belongs in CB_ADMIN_ALWAYS_CONFIRM](#what-belongs-in-cb_admin_always_confirm)
- [Decision table: "I want to do X"](#decision-table-i-want-to-do-x)

## The shape of it

Administrative operations reshape a cluster, so the server layers independent
controls rather than relying on one:

1. **Read-only mode** decides which tools exist at all.
2. **Dry run** decides whether an allowed call is actually performed.
3. **Confirmation** decides whether a write proceeds, and who authorized it.
4. **The hard ceiling** decides which operations a machine may never authorize
   on its own, regardless of the above.

The layers are not alternatives. A production deployment normally runs all four.

Two deployment profiles (`workstation` and `enterprise`) set the posture these
controls operate in; see `references/configuration.md`.

## Layer 1 — read-only mode

`CB_ADMIN_READ_ONLY_MODE=true` is the default and the outermost guard.

The critical property: in read-only mode every mutating tool is **not loaded**.
It is absent from the tool list, not merely refused at call time. An agent cannot
call a tool it never sees, cannot be argued into calling it, and cannot discover
it by enumeration.

Classification is by annotation. Each tool carries `readOnlyHint` /
`destructiveHint`, and the dispatch treats a tool as write-side **unless it is
explicitly annotated read-only** — unannotated means unknown intent, which gets
the stronger gate.

Practical consequences for an agent:

- If a write tool appears to be missing, the correct report is "this server is
  read-only" or "this tool is disabled", **not** "that tool does not exist". The
  server's own refusal text names `CB_ADMIN_READ_ONLY_MODE` and
  `CB_ADMIN_DISABLED_TOOLS` as the likely causes.
- Enabling writes is a deployment decision made by a human editing server
  configuration and restarting. It is not something to negotiate mid-session.
- `cb_mcp_status` reports the current mode, and `cb_mcp_list_tools` reports what
  is actually loaded. Ask the server; never infer posture from a failure.

`CB_ADMIN_DISABLED_TOOLS` removes named tools independently of read-only mode, so
a deployment can enable writes and still withhold specific operations entirely.

## Layer 1a — dry run

Every write tool accepts `dry_run: true`, and `CB_ADMIN_DRY_RUN=true` forces it
server-wide for every call.

What a dry run does: the call is authorized and audited normally, and then **not
performed**. The response states which tool would have run, against which target,
with which arguments.

What it does not do — this matters and is easy to overstate:

- **A dry run validates the request, not the cluster's acceptance of it.** The
  payload is never sent. It tells you what the agent decided to do, not whether
  the cluster would succeed. A bucket create that would fail on insufficient
  memory quota still previews cleanly.
- **A dry run is not authorization.** All the gates run *first* — scope, hard
  ceiling, confirmation — precisely so that a dry run cannot be used to discover
  what a tool you are not allowed to call would do.

**The environment variable wins over the argument.** `dry_run: false` supplied by
a caller cannot escape a server-wide preview mode. A forced preview is an
operator control, not a default a client can override.

**Reads still execute.** Refusing them would remove the information a plan is
checked against. Only write-side calls are withheld.

Use it for the first unattended run against a new organization or cluster, and
keep the preview output as the artifact attached to the change request.

Two wrinkles worth knowing:

- A few tools implement `dry_run` themselves rather than letting the dispatch
  intercept it. `cb_mcp_status` reports that set under `safety.dry_run.handler_owned`
  — it cannot be inferred from the advertised schemas.
- `capella_env_reap` is one of those tools and its own `dry_run` **defaults to
  true**. It reports what it would tear down and deletes nothing until `dry_run`
  is explicitly false.

## Layer 2 — confirmation, and the two ways to satisfy it

When writes are enabled, **every write tool is gated by default** — not only the
destructive subset. The default confirmation set is built from every tool that is
not annotated read-only.

There are two distinct ways past the gate, and they encode different trust models.

### Interactive — a human approves each call

The default, and the right model when a person is driving. A gated call is
withheld until the caller supplies `confirm: true` in the arguments, or answers an
elicitation prompt on clients that support one.

Because it is confirmation-by-argument, it works on **any** MCP client, with no
dependency on elicitation protocol support.

In the `workstation` profile, `confirm: true` means a person really looked: the
MCP client surfaces each call. In the `enterprise` profile it means nothing on its
own — the model supplies the argument — which is why that profile authorizes
writes differently.

### Automation — an authorized principal runs unattended

For CI/CD and workflow agents where no human is present per call. A pipeline that
seeds an environment or promotes a build cannot stop for approval on every bucket
create.

The wrong fixes are to have the agent impersonate a human by auto-answering, or to
switch confirmation off. Both destroy the gate. This server instead binds
automation to the **authenticated principal**:

- The workflow's service principal is issued a token by your IdP carrying the
  automation scope (`couchbase-admin-mcp:automation`) **in addition to** the write
  scope.
- A session on that token executes ordinary gated writes without a per-call
  prompt, because the human decision already happened once, at credential
  issuance. That is the auditable authorization.
- The automation scope **never substitutes** for the write scope. An automation
  token without write scope still cannot write.
- The scope is bound to the token and issued by your IdP, so **a caller cannot
  self-promote** by putting a value in tool arguments.

Scope enforcement requires the HTTP transport with `OAUTH_ISSUER` configured and
`CB_ADMIN_HTTP_REQUIRE_AUTH=true`. Without those, there is no token, and therefore
no automation mode.

## Layer 3 — the hard ceiling

`CB_ADMIN_ALWAYS_CONFIRM` is a server-configured list of tools that **always**
require a per-call human confirmation, **even for an automation-scoped principal**.

This is the control that makes automation mode safe to offer. Its properties:

- The list is set on the **server**, at deploy time, by a human.
- No token scope, no tool argument, no client-supplied value can remove a tool
  from it.
- It is evaluated **unconditionally and before anything else** — it is not
  conditional on whether the session holds automation scope. (An earlier design
  that gated the ceiling on automation scope inverted the privilege model: a
  principal holding write but not automation skipped the ceiling entirely.)
- It ships **empty**, so a developer's own cluster is friction-free out of the box.

**It is only satisfiable over stdio.** The ceiling demands evidence that a human is
present at the moment of action, and stdio — where the MCP client surfaces the call
to a person who answers the prompt — is the only transport that supplies it. Over
HTTP, where the caller is a token, a ceiling tool is refused outright rather than
being satisfiable by any argument. That is the intended behaviour: the whole point
is that an unattended pipeline provably cannot perform these operations.

A ceiling entry that matches no loaded tool protects nothing. Names are
case-sensitive, and the server prints a startup warning naming any entry that
matches no tool. Check that warning after editing the list.

## Order of evaluation

For a single `tools/call`, in order:

1. Handler exists?
2. Tool is in the currently loaded set? (read-only mode, disabled tools,
   deployment-mode gating)
3. OAuth scope check for the tool (no-op on stdio / without OAuth).
4. **Hard ceiling** — refused if no human is present.
5. Confirmation gate — `confirm: true`, or automation scope for non-ceiling tools.
6. `confirm` and correlation-id control fields stripped from the arguments so they
   never reach a REST body.
7. **Dry run** — withheld here if in effect and the call is write-side.
8. Execute.

Every refusal is reported to the client as a protocol-level error (`isError: true`),
not as a successful call whose text happens to describe a failure.

## Per-environment policy

Because the ceiling and the rest of the posture are server configuration, one
binary enforces different policy per environment. The development cluster's server
can run permissive automation with an empty ceiling; the production cluster's
server keeps promotion-to-production operations behind the hard gate. **Deploy the
same image, change the config.**

This is the reason not to build policy into prompts or agent instructions: an agent
pointed at the production server inherits the production posture automatically, and
cannot talk its way out of it.

## Capella guardrails — a separate, parallel control

The four layers above do not express "delete freely, but only inside the sandbox",
which is exactly what ephemeral-environment teardown needs. Capella therefore has
its own server-side limits, which no tool argument, token scope, or model assertion
can relax:

- `CAPELLA_ORG_ID` pins the organization; a conflicting caller override is refused.
- `CAPELLA_ALLOWED_PROJECTS` confines destructive operations to listed projects.
  **Unset means fail closed** — the server will create but refuse to delete.
- `CAPELLA_ENV_NAME_PREFIX` refuses destructive operations on any resource whose
  name lacks the prefix, covering a hand-made cluster sitting in an allowlisted
  project.
- `CAPELLA_MAX_ENVIRONMENTS` caps how many managed environments can exist, so a
  retry loop cannot provision without bound.
- `CAPELLA_PROTECTED_CLUSTERS` names individual exceptions.
- Capella's own deletion-protection flag is honored and cannot be overridden here.

Ask the running server what its posture actually is with `capella_guardrails_status`
— it is answered by the same code that enforces the policy, so it cannot drift from
documentation. Check it first whenever a Capella write is unexpectedly refused.

## Audit

Every gated call is logged with the tool name, redacted arguments, outcome
(decision), and duration. When an OAuth token is present, the principal and the mode
it ran under — interactive or automation — are recorded, so "a pipeline did this
unattended" is accountable rather than opaque.

Decisions are distinguished, not collapsed:

- `allowed` — the call executed.
- `dry_run` — the call was previewed and **not** performed. A preview never counts
  as a privileged write in the record.
- `denied_confirmation`, `denied_scope`, `denied_read_only`, `denied_deployment`,
  `denied_unknown_tool` — refusals, each naming its reason.
- `error` — the handler raised.

A handler that refuses on its own (egress allowlist, a Capella guardrail, a
validation error) is classified from its result rather than being recorded as
`allowed`, so a refused log-bundle upload is not indistinguishable from a successful
bucket delete.

Sensitive fields — passwords, tokens, secrets, KMIP passphrases — are redacted from
both logs and error responses. A failed `admin_user_create` never echoes the
plaintext password back to the agent or into a log file. Connection-string userinfo
is masked at the source, so `cb_mcp_status` does not leak a password embedded in a
URI.

If an audit sink was asked for and cannot be opened, the server **refuses to start**
rather than falling back to the log file the operator was told to stop reading.

## What belongs in CB_ADMIN_ALWAYS_CONFIRM

The README's worked example for a production admin server:

```bash
CB_ADMIN_ALWAYS_CONFIRM=admin_bucket_delete,admin_bucket_flush,admin_node_remove,\
admin_failover_hard,admin_failover_graceful,admin_rebalance_start,\
admin_user_delete,admin_xdcr_replication_delete
```

Why each earns its place:

| Tool | Why it must stop for a human |
|---|---|
| `admin_bucket_delete` | Deletes a bucket and all its data. Irreversible; nothing in this server can put it back. |
| `admin_bucket_flush` | Empties a bucket in place. Irreversible, and the bucket keeps existing, so the failure looks like data loss rather than a missing bucket. |
| `admin_node_remove` | Ejects a node. Combined with a rebalance it moves data cluster-wide; on an under-replicated bucket it can remove the only copy. |
| `admin_failover_hard` | Forcibly removes a node. Explicitly may cause data loss for unreplicated documents. |
| `admin_failover_graceful` | Safer than hard failover but still reduces capacity and changes topology under load. |
| `admin_rebalance_start` | Moves data across the whole cluster and stresses it for as long as it runs. The blast radius is every bucket at once. |
| `admin_user_delete` | Removes a credential. Anything authenticating as that user fails immediately, and the roles are not recoverable from here. |
| `admin_xdcr_replication_delete` | Stops replicating to the target. The target silently stops converging, and the gap is only discovered later. |

Strong additional candidates, on the same reasoning:

| Tool | Why |
|---|---|
| `admin_kmip_set` | Repoints where the cluster fetches its master encryption key. Aimed wrong, the cluster cannot decrypt its own data after a restart. |
| `admin_encryption_set` | Misconfiguration can render data unreadable. |
| `admin_security_settings_set` | TLS minimum version and cipher suites — misconfiguration can lock every client, including you, out of the cluster. |
| `admin_internal_settings_set` | Advanced tunables; the tool's own description says misconfiguration can wedge a cluster. |
| `admin_backup_restore_run` | Overwrites data in the target cluster. The only backup tool that destroys anything. |
| `admin_cluster_memory_set` | Service memory quotas; misconfiguration can crash services. |
| `admin_logs_collect_start` | Makes every node gather a diagnostic bundle and upload it to a caller-named host. One call is "send me all your logs." |
| `admin_scope_delete` / `admin_collection_delete` | Irreversible data removal at a finer grain than a bucket, and correspondingly easier to do by accident. |
| `admin_eventing_delete` | Removes function source code irreversibly. |

Two cautions:

- **Do not put Capella teardown tools in the ceiling on a sandbox server.**
  `capella_env_reap` and `capella_env_teardown` exist to run unattended; a ceiling
  entry stops them dead and orphaned environments then persist. Confine them with
  the Capella guardrails instead.
- **The README's example list also names `admin_cluster_leave`, which matches no
  tool in the current source.** Entries that match nothing protect nothing; the
  server warns about them at startup. Verify every name in your list against
  `cb_mcp_list_tools` for the build you are actually running.

## Decision table: "I want to do X"

| You want to | The gate you must pass |
|---|---|
| Read anything (list buckets, read stats, EXPLAIN a query) | Nothing. Reads load in every mode and execute even under a forced dry run. |
| Call any write tool at all | The tool must be **loaded**: `CB_ADMIN_READ_ONLY_MODE=false`, and not named in `CB_ADMIN_DISABLED_TOOLS`. Requires a server restart to change. |
| Preview a write without performing it | Pass `dry_run: true`. Nothing else needed — but the gates below still run first. |
| Perform a write while a human drives | Supply `confirm: true` (or answer the client's elicitation prompt). |
| Perform a write unattended | HTTP transport + `OAUTH_ISSUER` + `CB_ADMIN_HTTP_REQUIRE_AUTH=true`, and a token carrying **both** the write scope and `couchbase-admin-mcp:automation`. |
| Perform a write unattended when `CB_ADMIN_DRY_RUN=true` | Not possible. The env var wins; `dry_run: false` cannot escape it. Change the server config. |
| Perform a tool listed in `CB_ADMIN_ALWAYS_CONFIRM` | A per-call human confirmation over **stdio**. No scope, argument, or client value substitutes. Over HTTP it is refused outright. |
| Remove a tool from the hard ceiling | Edit the server's environment and restart. Nothing in-session can do it. |
| Delete a Capella cluster or environment | Guardrails, not the confirmation layer: allowlisted project, name carries `CAPELLA_ENV_NAME_PREFIX`, Capella deletion protection off, and the cluster not in `CAPELLA_PROTECTED_CLUSTERS`. |
| Point the cluster at an outbound host (log upload, XDCR target, KMIP, SMTP) | The destination must satisfy the egress allowlist (`CB_ADMIN_EGRESS_ALLOWED_HOSTS`). Loopback, link-local and cloud-metadata addresses are always refused. |
| Find out which of these applies right now | `cb_mcp_status`, `cb_mcp_list_tools`, and `capella_guardrails_status`. Ask the server; never infer from a failure. |
