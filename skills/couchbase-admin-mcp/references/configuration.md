# Configuration

Every environment variable the Couchbase Admin MCP server reads, what it does, its
default, and what goes wrong when it is set incorrectly — plus the Docker and Claude
Desktop wiring. Nothing here is invented: each variable below appears in the server's
README or its source. Where a default is not stated by the source, this file says
"not stated" rather than supplying one.

## Contents

- [The one variable with no default](#the-one-variable-with-no-default)
- [Deployment profiles](#deployment-profiles)
- [Connection and credentials](#connection-and-credentials)
- [Cluster TLS and mTLS](#cluster-tls-and-mtls)
- [Safety controls](#safety-controls)
- [Transport](#transport)
- [Server-side TLS for the HTTP transport](#server-side-tls-for-the-http-transport)
- [OAuth and bearer-token enforcement](#oauth-and-bearer-token-enforcement)
- [Outbound egress allowlist](#outbound-egress-allowlist)
- [Logging](#logging)
- [Local filesystem roots](#local-filesystem-roots)
- [Capella](#capella)
- [Docker and compose](#docker-and-compose)
- [Claude Desktop wiring](#claude-desktop-wiring)
- [Startup failure modes, collected](#startup-failure-modes-collected)

## The one variable with no default

`CB_ADMIN_PROFILE` has **no default and the server refuses to start without it**:

```
[couchbase-admin-mcp] REFUSING TO START: CB_ADMIN_PROFILE is not set.
```

That is deliberate. The two supported deployments have opposite security postures,
and guessing between them is how you end up with an unauthenticated administration
API on a network interface.

| Variable | Values | Default | Failure mode |
|---|---|---|---|
| `CB_ADMIN_PROFILE` | `workstation`, `enterprise` | **none** | Server exits at startup with the message above. |

## Deployment profiles

| | `workstation` | `enterprise` |
|---|---|---|
| Shape | Laptop or local container, driven by an MCP client over stdio | A workflow-manager agent instructs child agents, which act unattended |
| Human present at the moment of action? | **Yes** — the MCP client surfaces each call | **No, by design** |
| `confirm: true` means | A person really looked | Nothing — the model supplies it |
| What authorizes a write | That confirmation | The automation scope in the caller's OAuth token |
| Identity in the audit record | OS user and host | The token's service principal |
| HTTP auth | Off (there is no IdP on a laptop) | **Required** |
| Admin console | Loopback only, peer-address checked | Behind SSO |

The profile derives the whole posture from that single variable, and the server
**refuses incoherent combinations at startup** rather than at 3am. The pairing that
matters most: `CB_ADMIN_PROFILE=workstation` with `CB_ADMIN_TRANSPORT=http` on a
**non-loopback** address is fatal, because every relaxation the workstation profile
makes is justified by nothing being network-reachable.

Two explicit acknowledgements exist for the container case, and both are deliberately
awkward:

| Variable | Purpose | Default | Failure mode |
|---|---|---|---|
| `CB_ADMIN_WORKSTATION_CONTAINER_BIND` | States that a non-loopback bind is a container publishing its port narrowly to the host, not a network exposure. Inside a container the process *must* bind `0.0.0.0`; the isolation comes from publishing the port as `127.0.0.1:8000:8000`, not from the bind address. | unset | Without it, `workstation` + http + non-loopback host refuses to start. |
| `CB_ADMIN_TLS_TERMINATED_EXTERNALLY` | States that this listener is deliberately cleartext because something in front terminates TLS. Acceptable on a private network you control; **not** acceptable anywhere a bearer token could be observed. | unset | Without it (and without a certificate), a non-loopback HTTP bind refuses to start. |

## Connection and credentials

| Variable | Purpose | Default | Failure mode |
|---|---|---|---|
| `CB_CONNECTION_STRING` | Cluster connection string. Use `couchbase://` for non-TLS in-network, `couchbases://` for TLS. | `couchbase://localhost` | Points the server at the wrong cluster silently; every admin call then acts on it. A Capella connection string is detected and the `admin_*` tools are unloaded. |
| `CB_USERNAME` | Cluster admin username. | required unless using mTLS | Admin calls fail to authenticate. |
| `CB_PASSWORD` | Cluster admin password. | required unless using mTLS | As above. Redacted from logs and error responses. |
| `CB_BUCKET` | Default bucket for the SDK warm-up used by a few diagnostics tools. Admin operations act at cluster level, so it is optional. | `default` | Diagnostics tools that need a bucket have nothing to open. |
| `CB_SCOPE` | Default scope. | `_default` | As above. |
| `CB_COLLECTION` | Default collection. | `_default` | As above. |
| `CB_MGMT_PORT` | Management REST port (`8091`, or `18091` for TLS). | `8091` | Admin REST calls go to the wrong port and fail to connect. |
| `CB_EVENTING_PORT` | Eventing service port override, for environments whose Eventing API is not at the default prefix. | not stated | Eventing tools address the wrong endpoint. |

Credentials matter twice over: a password embedded in the connection-string userinfo
is masked at source, so `cb_mcp_status` does not return it.

## Cluster TLS and mTLS

These describe how this server talks to the **cluster**.

| Variable | Purpose | Default | Failure mode |
|---|---|---|---|
| `CB_CLIENT_CERT_PATH` | Client certificate PEM. Its **presence enables mTLS**. | unset | Set without the key, mTLS cannot be established. |
| `CB_CLIENT_KEY_PATH` | Client key PEM. | unset | As above. |
| `CB_CA_CERT_PATH` | CA certificate for a self-signed self-managed cluster. | unset | TLS verification fails against a private CA. |
| `CB_ADMIN_TLS_INSECURE` | Skip TLS verification. **Development only.** | `false` | True in a shared deployment removes certificate verification for cluster calls. |

## Safety controls

Covered in depth in `references/safety-and-trust.md`; the variables themselves:

| Variable | Purpose | Default | Failure mode |
|---|---|---|---|
| `CB_ADMIN_READ_ONLY_MODE` | When true, write tools are **not loaded** at all. | `true` | Set to `false` without a confirmation policy and every write tool becomes callable with `confirm: true`. |
| `CB_ADMIN_DRY_RUN` | Forces preview mode for every write call, server-wide. The env var wins over a caller's `dry_run: false`. | not stated as a value; the behaviour is documented as opt-in | Left on in production, no write ever happens while every call reports success as a preview. Observable via `cb_mcp_status`. |
| `CB_ADMIN_DISABLED_TOOLS` | Comma-separated tool names, **or a path to a file** with one name per line. Those tools are unloaded. | empty | A misspelled name disables nothing; the tool stays loaded. |
| `CB_ADMIN_CONFIRMATION_REQUIRED_TOOLS` | Adjusts which tools require `confirm: true`, relative to the default set (every write tool). | defaults to every write tool | Narrowing this removes the per-call gate from tools it names. |
| `CB_ADMIN_ALWAYS_CONFIRM` | The hard ceiling: tools that always require per-call human confirmation, even for an automation principal. Only satisfiable over stdio. | **empty** | An entry matching no loaded tool protects nothing; the server prints a startup warning naming it. Names are case-sensitive. |
| `CB_ADMIN_ELICITATION_HINTS` | Include hint text in confirmation errors. | `true` | Off, refusals say less about how to proceed. |

## Transport

| Variable | Purpose | Default | Failure mode |
|---|---|---|---|
| `CB_ADMIN_TRANSPORT` | `stdio` or `http`. stdio is the default in both the code and the Docker image. | `stdio` | stdio cannot cross a container boundary — a networked service left on stdio is unreachable. |
| `CB_ADMIN_HOST` | Bind address for the http transport. | `127.0.0.1` | `0.0.0.0` without auth exposes the full admin tool surface unauthenticated; the server refuses to start in the combinations described above. |
| `CB_ADMIN_PORT` | Listen port for the http transport. | `8000` | Port collision, or clients pointed at the wrong port. |
| `CB_ADMIN_ALLOWED_ORIGINS` | Comma-separated allowed browser origins. | unset | Over-broad values weaken cross-origin protection for the HTTP endpoint. |
| `CB_ADMIN_ALLOWED_HOSTS` | Comma-separated allowed `Host` values — DNS-rebinding protection. | unset | Unset on a non-loopback bind, the server warns that rebinding protection will reject requests; set it to the names clients actually use. |

## Server-side TLS for the HTTP transport

| Variable | Purpose | Default | Failure mode |
|---|---|---|---|
| `CB_ADMIN_TLS_CERT_FILE` | Certificate for terminating TLS in this server. | unset | Non-loopback HTTP with neither a certificate nor `CB_ADMIN_TLS_TERMINATED_EXTERNALLY` refuses to start — cleartext bearer tokens defeat every other control at once. |
| `CB_ADMIN_TLS_KEY_FILE` | Matching private key. | unset | Cert without key cannot terminate TLS. |
| `CB_ADMIN_TLS_TERMINATED_EXTERNALLY` | Declares that a proxy or mesh in front terminates TLS, so this listener may be cleartext. | unset | Set where it is not true, bearer tokens travel in the clear. |

## OAuth and bearer-token enforcement

| Variable | Purpose | Default | Failure mode |
|---|---|---|---|
| `OAUTH_ISSUER` | IdP issuer. Enables bearer-token validation on the HTTP transport. | unset | Set **without** `CB_ADMIN_HTTP_REQUIRE_AUTH=true`, invalid or missing tokens are silently ignored — the server prints a startup warning saying exactly that. |
| `OAUTH_AUDIENCE` | Expected token audience. | unset | A token minted for another audience is accepted if audience is not checked. |
| `CB_ADMIN_HTTP_REQUIRE_AUTH` | Enforce bearer-token validation and per-tool scope enforcement (including automation mode) on HTTP. | `false` | Off, the server performs **no request auth** on HTTP: keep it on a trusted internal network or behind a proxy. |
| `OAUTH_SKIP_VERIFY` | Disables JWT signature, issuer, audience and expiry verification. Local development only. | off | **Never set in production.** Any token is accepted and any caller can self-grant write and automation scope, making the entire trust model meaningless. The server prints a loud startup banner when it is on. |

Automation mode exists only where tokens exist. Over stdio there is no token, so
scope enforcement is a no-op and the interactive confirmation model applies.

## Outbound egress allowlist

Several admin operations take a hostname from the caller and make **Couchbase
itself** open the connection — log-bundle upload, XDCR remote references, node add,
KMIP, SMTP alerts. That inverts the direction of control, so destinations are
allowlisted before any such call is issued.

| Variable | Purpose | Default | Failure mode |
|---|---|---|---|
| `CB_ADMIN_EGRESS_ALLOWED_HOSTS` | Comma-separated hosts, IPs or CIDRs the cluster may be pointed at. A leading dot is a domain suffix match, e.g. `.couchbase.com,10.20.0.0/16,smtp.corp.example`. | empty | **Fail closed**: with it empty, those operations are refused with a message naming this variable. |
| `CB_ADMIN_EGRESS_ALLOW_ANY` | Escape hatch for **public** destinations only. Does not admit private/RFC1918 ranges, loopback, link-local or cloud-metadata addresses. | off | Convenient and conspicuous by design; it still cannot turn the cluster into a reverse proxy into the internal network. |
| `CB_ADMIN_EGRESS_SKIP_DNS` | Disables the DNS resolution check that catches a name resolving to a denied address. | on (checking enabled) | Set true only where DNS is unavailable to the server; doing so removes a real control. |
| `CB_ADMIN_EGRESS_EXEMPT_FIELDS` | Additional argument field names exempt from host checking. | empty | Exempting a field that really does carry a destination removes the allowlist for that operation. |

Loopback, link-local and cloud metadata addresses are **always refused**, even under
`CB_ADMIN_EGRESS_ALLOW_ANY`.

## Logging

Logs use a per-module hierarchy under `couchbase-admin.*`, configured through the
`CB_ADMIN_LOG_*` family. With the file sink enabled the server writes **one rotating
file per level**:

- `cb_admin_mcp.info.log`
- `cb_admin_mcp.warning.log`
- `cb_admin_mcp.error.log`

One file per level exists so support can request exactly the error log without
wading through everything else. Tracebacks are written to the error log — that is the
record to send with a support request.

Sensitive fields (passwords, tokens, secrets, KMIP passphrases) are redacted from
both logs and error responses.

> **Not verifiable from the staged source:** the individual variable names inside
> the `CB_ADMIN_LOG_*` family and their defaults live in `.env.example`, which is not
> part of the staged material. Read `.env.example` in the repository for the exact
> names. Do not guess them.

The startup banner and all warnings go to **stderr**, so they do not pollute stdio
MCP framing.

## Local filesystem roots

Two tool families write to local disk rather than to a cluster.

| Variable | Purpose | Default | Failure mode |
|---|---|---|---|
| `CB_ADMIN_CATALOG_ROOT` | Where the backup catalogue (`cb_backup_catalog_*`) stores its entries, one file per entry. | reads fall back to a `.backup-catalog` directory; **writes are refused** unless this is set or `catalog_root` is passed | Unset in a container, a relative default would land in the image layer and vanish on restart — so the server refuses to write instead, and says so. Point it at a mounted volume. |
| `CB_ADMIN_FIXTURE_ROOT` | Confines where `capella_fixture_*` may read and write fixture files. | unset, meaning any absolute path | Correct default for a developer workstation, wrong for a shared container: set it in any deployment where the caller is not the operator. Paths outside the root are refused. |

## Capella

Capella credentials and guardrails are separate from cluster credentials. A Capella
**database credential** carries bucket-scoped data roles and never Full Admin, so the
`admin_*` tools cannot work against Capella at all — the server detects a Capella
connection string and unloads them rather than offering tools that each fail with an
opaque 401.

| Variable | Purpose | Default | Failure mode |
|---|---|---|---|
| `CAPELLA_API_KEY_SECRET` | Organization API key secret, sent as a Bearer token to the Management API v4. | unset | Every `capella_*` call is unauthenticated. `capella_organizations_list` is the cheapest call that proves the token is valid. |
| `CAPELLA_ORG_ID` | Pins the organization. A conflicting caller override is refused. | unset | Unset, `organization_id` must be supplied per call. |
| `CAPELLA_DEFAULT_PROJECT_ID` | Default project when a call omits `project_id`. | unset | Calls that omit the project are refused with a message naming this variable. |
| `CAPELLA_ALLOWED_PROJECTS` | Project UUIDs in which destructive operations are permitted. | unset | **Unset means fail closed**: the server will create but refuse to delete, and says so in the startup banner. Renaming a project does not move it in or out of this list — the UUID is what counts. |
| `CAPELLA_ENV_NAME_PREFIX` | Destructive operations refuse any resource whose name lacks this prefix. | unset | Unset, a hand-made cluster inside an allowlisted project is not protected by name. |
| `CAPELLA_MAX_ENVIRONMENTS` | Ceiling on managed environments, so a retry loop cannot provision without bound. | not stated | Too high, a crash loop provisions repeatedly. |
| `CAPELLA_PROTECTED_CLUSTERS` | Named clusters that destructive operations always refuse. | unset | Names are matched as configured; a mismatch protects nothing. |
| `CAPELLA_ENV_TTL_HOURS` | Default TTL stamped on a managed environment, used by `capella_env_reap`. | a source comment names **8** hours | Long TTLs leave expired environments running until the next reap. |
| `CAPELLA_MAX_ITEMS` | Page size cap for paginated v4 listings. Results are auto-paginated. | not stated | Very low values make large listings slow; the tools report truncation. |
| `CB_CAPELLA_CLUSTER_USER` | A **cluster access** credential username (the kind `capella_database_credential_create` issues) for Data API calls used by the fixture tooling. | unset | Setting only the API key produces a 401 from the Data API with no hint which secret is missing. |
| `CB_CAPELLA_CLUSTER_PASSWORD` | Matching password. | unset | As above. |

`capella_guardrails_status` reports the effective posture from the same code that
enforces it. Call it first whenever a Capella write is unexpectedly refused.

## Docker and compose

Build:

```bash
docker build -t couchbase-admin-mcp:latest .
```

To reach a cluster in another container, put both on the same Docker network and
point `CB_CONNECTION_STRING` at the cluster container's service name. For a
long-running networked service you **opt in to HTTP** — stdio cannot cross a
container boundary.

```yaml
# docker-compose.yml
services:
  couchbase:
    image: couchbase:enterprise
    ports: ["8091-8096:8091-8096", "11210:11210"]
    # ... your cluster provisioning ...

  admin-mcp:
    build: .
    depends_on: [couchbase]
    ports: ["8000:8000"]
    environment:
      CB_ADMIN_PROFILE: workstation     # no default; the server refuses to start without it
      CB_CONNECTION_STRING: couchbase://couchbase   # the service name above
      CB_USERNAME: Administrator
      CB_PASSWORD: password
      CB_ADMIN_READ_ONLY_MODE: "false"  # opt in to writes (default is true/read-only)
      CB_ADMIN_TRANSPORT: http          # opt in to HTTP for a networked service
      CB_ADMIN_HOST: 0.0.0.0            # accept connections from other containers/host

      # The two acknowledgements this combination requires. Both are deliberately
      # awkward: `workstation` + HTTP + a non-loopback bind is exactly the shape that
      # produces unauthenticated admin over a network, so the server will not start
      # unless you state that you know what you are doing and why.
      CB_ADMIN_WORKSTATION_CONTAINER_BIND: "1"
      CB_ADMIN_TLS_TERMINATED_EXTERNALLY: "1"

      # For unattended automation on a shared cluster use CB_ADMIN_PROFILE=enterprise
      # instead, which requires OAuth and refuses hard-ceiling tools outright.
```

Clients then connect to `http://<host>:8000/mcp`.

Notes carried from the README:

- The image runs as a non-root user and ships **read-only by default**.
- Publish the port as `127.0.0.1:8000:8000` if the host should be the only client.
- Use `couchbase://` for a non-TLS in-network connection, or supply certificates and
  keep `couchbases://` for TLS.
- On HTTP with no OAuth configured the server performs **no request auth**. Keep it
  on a trusted internal network or put a proxy in front. With `OAUTH_ISSUER` plus
  `CB_ADMIN_HTTP_REQUIRE_AUTH=true`, bearer-token scope enforcement — including
  automation mode — applies.

## Claude Desktop wiring

Claude Desktop speaks **stdio** natively and does not connect directly to a private
HTTP MCP endpoint: its custom-connector feature routes the URL through a cloud
service that cannot reach a server on a private network — and a cluster-admin server
should not be exposed publicly to make it reachable. Two setups work.

### Option A — stdio (simplest)

Let Claude Desktop launch the container per session and speak stdio directly. The
container still reaches the Couchbase container over the Docker network for the
*cluster* connection; only the MCP channel is stdio.

```json
{
  "mcpServers": {
    "couchbase-admin": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--network", "your_docker_network",
        "-e", "CB_ADMIN_PROFILE=workstation",
        "-e", "CB_ADMIN_TRANSPORT=stdio",
        "-e", "CB_CONNECTION_STRING=couchbase://couchbase",
        "-e", "CB_USERNAME=Administrator",
        "-e", "CB_PASSWORD=password",
        "-e", "CB_ADMIN_READ_ONLY_MODE=false",
        "couchbase-admin-mcp:latest"
      ]
    }
  }
}
```

`--network your_docker_network` is what lets the launched container resolve the
`couchbase` service name. stdio is the image default, so the transport variable is
shown only for clarity.

This is also the transport where `CB_ADMIN_ALWAYS_CONFIRM` can actually be satisfied.

### Option B — HTTP plus a local bridge

If the admin server runs as a persistent service, bridge it into Claude Desktop with
`mcp-remote`. The bridge runs on your machine, reaches the container locally, and
presents stdio to Claude Desktop — nothing needs public exposure.

```json
{
  "mcpServers": {
    "couchbase-admin": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:8000/mcp", "--allow-http"]
    }
  }
}
```

`--allow-http` is required because the container serves plain HTTP on localhost. With
OAuth enabled, add `--header "Authorization:Bearer <token>"`.

Restart Claude Desktop after editing the config and verify the server shows
**Connected** under Settings → Developer. If it does not, run the exact command from
the config manually in a terminal — the error it prints is far more useful than the
status line.

## Startup failure modes, collected

The server prefers to fail at boot rather than at 3am. It refuses to start when:

- `CB_ADMIN_PROFILE` is unset.
- The profile and the rest of the posture are incoherent — notably `workstation` +
  `http` + a non-loopback bind without `CB_ADMIN_WORKSTATION_CONTAINER_BIND`.
- A non-loopback HTTP bind has neither a server certificate nor
  `CB_ADMIN_TLS_TERMINATED_EXTERNALLY`.
- An audit sink was configured and cannot be opened.
- The declared deployment mode does not match what the configuration actually
  describes (for example, a Capella key and a non-Capella connection string both
  present by inheriting an env file).

It starts but warns loudly when:

- `OAUTH_ISSUER` is set without `CB_ADMIN_HTTP_REQUIRE_AUTH=true`.
- `OAUTH_SKIP_VERIFY` is enabled.
- `CB_ADMIN_ALWAYS_CONFIRM` names entries matching no loaded tool.
- `CB_ADMIN_ALLOWED_HOSTS` is unset on a binding that needs rebinding protection.
- Capella writes are enabled but `CAPELLA_ALLOWED_PROJECTS` is unset, so destructive
  Capella operations are refused fail-closed.
