# Configuration — installing, connecting, and running the server

Everything needed to get the official Couchbase MCP server (`couchbase/mcp-server-couchbase`) running and talking to a cluster.

## Contents

- [Prerequisites](#prerequisites)
- [Running the server](#running-the-server)
- [Environment variables](#environment-variables)
- [Client configuration](#client-configuration)
- [Transports](#transports)
- [OAuth 2.1 on HTTP transport](#oauth-21-on-http-transport)
- [Docker](#docker)
- [Logging](#logging)
- [Verifying the setup](#verifying-the-setup)
- [Decision tree](#decision-tree)

## Prerequisites

- **Python 3.10 or higher.**
- A running Couchbase cluster — Capella (fully managed) or self-managed Couchbase Server. Both use the same configuration.
- [`uv`](https://docs.astral.sh/uv/) installed, to run the server with `uvx`.
- An MCP client: Claude Desktop, Claude Code, Cursor, Windsurf, VS Code, JetBrains AI Assistant/Junie, or anything implementing the MCP specification.

There is **no npx or Node distribution**. The server is Python, distributed via PyPI and Docker. A config that invokes `npx` for this server is wrong and will fail.

## Running the server

Three supported ways:

**From PyPI (recommended)** — package `couchbase-mcp-server`:

```bash
uvx couchbase-mcp-server
```

**From source**:

```bash
git clone https://github.com/couchbase/mcp-server-couchbase.git
uv --directory path/to/mcp-server-couchbase/ run src/mcp_server.py
```

**From Docker** — `docker.io/couchbase/mcp-server`. See [Docker](#docker).

Check the version with `uvx couchbase-mcp-server --version`.

## Environment variables

Every setting has both an environment variable and a CLI argument. The environment variable is the usual choice for MCP client configs; the CLI argument suits shell invocation and containers.

### Connection and authentication

| Variable | CLI | Notes |
|---|---|---|
| `CB_CONNECTION_STRING` | `--connection-string` | **Required.** `couchbases://…` for TLS (always for Capella), `couchbase://…` for plaintext. |
| `CB_USERNAME` | `--username` | Required for basic auth. A Couchbase database user, not a Capella API key. |
| `CB_PASSWORD` | `--password` | Required for basic auth. |
| `CB_CLIENT_CERT_PATH` | `--client-cert-path` | Client certificate for mTLS — an alternative to username/password. |
| `CB_CLIENT_KEY_PATH` | `--client-key-path` | Client key for mTLS. |
| `CB_CA_CERT_PATH` | `--ca-cert-path` | Root CA for a self-signed or otherwise untrusted server certificate. Not needed for Capella. |

Supply **either** username/password **or** client certificate and key. If both are present, the client certificate wins.

### Safety and tool gating

| Variable | CLI | Default | Notes |
|---|---|---|---|
| `CB_MCP_READ_ONLY_MODE` | `--read-only-mode` | **`true`** | When true, the 12 write tools are not loaded and data/structure/privilege-modifying SQL++ is blocked. |
| `CB_MCP_DISABLED_TOOLS` | `--disabled-tools` | none | Tools to leave out of discovery entirely. |
| `CB_MCP_CONFIRMATION_REQUIRED_TOOLS` | `--confirmation-required-tools` | none | Tools that prompt the user via MCP elicitation before running. |

Both tool lists accept a comma-separated string or a path to a file with one tool name per line (`#` starts a comment). The file form is easier to maintain for more than a couple of entries. Details and recommended lists are in `security-best-practices.md`.

### Transport

| Variable | CLI | Default |
|---|---|---|
| `CB_MCP_TRANSPORT` | `--transport` | `stdio` — also `http`, `sse` |
| `CB_MCP_HOST` | `--host` | `127.0.0.1` (HTTP/SSE only) |
| `CB_MCP_PORT` | `--port` | `8000` (HTTP/SSE only) |

### Logging

`CB_MCP_LOG_LEVEL`, `CB_MCP_LOG_SINKS`, `CB_MCP_LOG_FILE`, plus rotation and retention controls (`CB_MCP_LOG_ROTATION_MAX_SIZE_MB`, `CB_MCP_LOG_RETENTION_BACKUP_COUNT`, and per-level overrides). See [Logging](#logging).

### OAuth

`CB_MCP_OAUTH_JWT_JWKS_URI`, `CB_MCP_OAUTH_JWT_ISSUER`, `CB_MCP_OAUTH_JWT_AUDIENCE`, `CB_MCP_OAUTH_JWT_ALGORITHM`, `CB_MCP_OAUTH_MCP_BASE_URL`, `CB_MCP_OAUTH_SCOPE_READ_LABEL`, `CB_MCP_OAUTH_SCOPE_WRITE_LABEL`. See [OAuth 2.1 on HTTP transport](#oauth-21-on-http-transport).

## Client configuration

The standard shape, using basic authentication:

```json
{
  "mcpServers": {
    "couchbase": {
      "command": "uvx",
      "args": ["couchbase-mcp-server"],
      "env": {
        "CB_CONNECTION_STRING": "couchbases://connection-string",
        "CB_USERNAME": "username",
        "CB_PASSWORD": "password"
      }
    }
  }
}
```

With mTLS, swap the username and password for the certificate paths:

```json
{
  "mcpServers": {
    "couchbase": {
      "command": "uvx",
      "args": ["couchbase-mcp-server"],
      "env": {
        "CB_CONNECTION_STRING": "couchbases://connection-string",
        "CB_CLIENT_CERT_PATH": "/path/to/client-certificate.pem",
        "CB_CLIENT_KEY_PATH": "/path/to/client.key"
      }
    }
  }
}
```

Client-specific notes:

- **Claude Desktop** — config at `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows). Restart after editing. Logs in `~/Library/Logs/Claude` or `%APPDATA%\Claude\Logs`.
- **Cursor** — Cursor Settings → Tools & Integrations → MCP Tools. Same JSON, under `mcpServers`.
- **VS Code** — `.vscode/mcp.json` for a workspace or the user config via **MCP: Open User Configuration**. VS Code uses **`servers`** as the top-level key, not `mcpServers`.
- **Windsurf** — Windsurf MCP Configuration Panel → Add custom server.
- **JetBrains IDEs** — Settings → Tools → AI Assistant or Junie → MCP Server.

If `uvx` is not on the client's PATH (common for GUI apps launched outside a shell), put the absolute path to `uvx` in `command`.

## Transports

**stdio** (default) — the client launches the server as a subprocess. One client per process. The right choice for a local desktop or IDE client. OAuth settings are ignored on stdio.

**http** (Streamable HTTP) — one running server shared by multiple clients over HTTP.

```bash
uvx couchbase-mcp-server \
  --connection-string='<connection_string>' \
  --username='<user>' --password='<password>' \
  --read-only-mode=true \
  --transport=http
```

Endpoint: `http://localhost:8000/mcp`. Client config is just a URL:

```json
{"mcpServers": {"couchbase-http": {"url": "http://localhost:8000/mcp"}}}
```

**Without OAuth configured, the HTTP endpoint is unauthenticated** — anyone who can reach the port gets the cluster credentials' full reach. Bind to `127.0.0.1` or put it behind authentication before exposing it.

**sse** — the older HTTP transport, **deprecated** by the MCP specification in favour of Streamable HTTP. Endpoint `http://localhost:8000/sse`. Use it only for a client that supports nothing newer.

## OAuth 2.1 on HTTP transport

On `--transport=http` the server can act as an OAuth 2.1 **resource server**: it validates incoming bearer JWTs against an identity provider's JWKS. It is provider-agnostic — any OAuth 2.1 / OIDC provider publishing a JWKS works. It does **not** issue tokens or manage users.

- OAuth activates only when all three of `CB_MCP_OAUTH_JWT_JWKS_URI`, `CB_MCP_OAUTH_JWT_ISSUER` and `CB_MCP_OAUTH_JWT_AUDIENCE` are set. Setting some but not all fails at startup.
- Two scopes are read from the token's `scope`/`scp` claim: `couchbase-mcp:read` for read tools including SQL++, and `couchbase-mcp:write` for write tools. Full access needs both. Override the labels with `CB_MCP_OAUTH_SCOPE_READ_LABEL` / `CB_MCP_OAUTH_SCOPE_WRITE_LABEL` if the IdP cannot emit the canonical forms.
- Setting `CB_MCP_OAUTH_MCP_BASE_URL` publishes RFC 9728 Protected Resource Metadata so PRM-aware clients can discover the IdP.
- Signing algorithm via `CB_MCP_OAUTH_JWT_ALGORITHM`: RS256/384/512, ES256/384/512, or PS256/384/512. Default RS256.

```bash
uvx couchbase-mcp-server \
  --connection-string='<connection_string>' \
  --username='<user>' --password='<password>' \
  --transport=http \
  --oauth-jwks-uri='https://auth.example.com/.well-known/jwks.json' \
  --oauth-issuer='https://auth.example.com/' \
  --oauth-audience='couchbase-mcp-server' \
  --oauth-mcp-base-url='<public_base_url>'
```

OAuth scopes gate which **tools** a caller may invoke. They do not change what the underlying Couchbase user can do — that is still RBAC.

## Docker

Prebuilt images: `docker pull docker.io/couchbase/mcp-server:latest`. The server is also in the Docker MCP Catalog.

Standalone, HTTP transport:

```bash
docker run --rm -i \
  -e CB_CONNECTION_STRING='<connection_string>' \
  -e CB_USERNAME='<user>' \
  -e CB_PASSWORD='<password>' \
  -e CB_MCP_TRANSPORT='http' \
  -e CB_MCP_READ_ONLY_MODE='true' \
  -e CB_MCP_PORT=9001 \
  -e CB_MCP_HOST=0.0.0.0 \
  -p 9001:9001 \
  couchbase/mcp-server
```

As a stdio server launched by a client:

```json
{
  "mcpServers": {
    "couchbase-mcp-docker": {
      "command": "docker",
      "args": ["run", "--rm", "-i",
        "-e", "CB_CONNECTION_STRING=<connection_string>",
        "-e", "CB_USERNAME=<user>",
        "-e", "CB_PASSWORD=<password>",
        "couchbase/mcp-server"]
    }
  }
}
```

`CB_MCP_PORT` and `CB_MCP_HOST` apply only to the HTTP and SSE transports. For a Couchbase Server running on the container host, the connection string is usually `couchbase://host.docker.internal`.

## Logging

Logs go to `stderr` by default.

- **`CB_MCP_LOG_LEVEL`** — `off`, `debug`, `info` (default), `warning`, `error`. `info` records lifecycle events and tool invocations; `debug` adds verbose internals.
- **`CB_MCP_LOG_SINKS`** — `stderr` (default), `file`, or both. With `file`, one rotating file is written per level (e.g. `mcp_server.info.log`, `mcp_server.error.log`) based on `CB_MCP_LOG_FILE`.
- **Rotation** — `CB_MCP_LOG_ROTATION_MAX_SIZE_MB` sets the global per-file rotation size in MB (default 1); per-level overrides are `CB_MCP_LOG_<LEVEL>_ROTATION_MAX_SIZE_MB`. A value of `0` is invalid and falls back to the default with a startup warning. `CB_MCP_LOG_MAX_BYTES` is deprecated and ignored when the MB setting is also present.
- **Retention** — `CB_MCP_LOG_RETENTION_BACKUP_COUNT` (default 1) sets rotated backups kept per level, with per-level overrides. `0` keeps only the live file.
- **Config snapshot** — with the `file` sink active, a one-shot JSON record (OS, Python, dependency versions, transport, resolved logging config, redacted server config) is written to `mcp_server_config.log.json`, overwritten on each start. Attach it to support requests.

```bash
uvx couchbase-mcp-server --log-level=debug --log-sinks=stderr,file
```

## Verifying the setup

In order, cheapest first:

1. **`get_server_configuration_status`** — reports read-only mode, disabled tools, confirmation-required tools, OAuth settings and resolved logging **without connecting to the cluster**. Run this first when the question is "is the server configured the way I think?"
2. **`test_cluster_connection`** — actually connects with the configured credentials. Optionally pass `bucket_name` to verify access to a specific bucket.
3. **`get_cluster_diagnostics_report`** — the SDK's cached connection state. No network I/O.
4. **`get_buckets_in_cluster`** — confirms the user can see at least one bucket. A user with no bucket access is a common cause of an apparently-working-but-useless setup.

## Decision tree

- **Local desktop or IDE client, one user** → `stdio` transport, PyPI package via `uvx`.
- **Several clients, or a remote/shared deployment** → `http` transport, and configure OAuth before exposing the port.
- **A client that only supports SSE** → `sse`, understanding it is deprecated.
- **Containerised deployment** → the Docker image, environment variables for everything.
- **Self-signed cluster certificate** → set `CB_CA_CERT_PATH`. Do not disable TLS.
- **Certificate-based auth instead of a password** → `CB_CLIENT_CERT_PATH` + `CB_CLIENT_KEY_PATH`, and drop `CB_USERNAME`/`CB_PASSWORD`.
- **Agent must not write** → leave `CB_MCP_READ_ONLY_MODE` at its default `true`, and give the Couchbase user read-only roles as well.
- **Server starts but no tools appear** → see `troubleshooting.md`.
