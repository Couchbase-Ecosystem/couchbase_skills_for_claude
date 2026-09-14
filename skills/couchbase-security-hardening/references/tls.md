# TLS configuration

## Contents

- [The three TLS surfaces](#the-three-tls-surfaces)
- [Minimum TLS version](#minimum-tls-version)
- [Cipher suites](#cipher-suites)
- [Cluster encryption level (node-to-node)](#cluster-encryption-level-node-to-node)
- [Certificates](#certificates)
- [Client certificate authentication (mTLS)](#client-certificate-authentication-mtls)
- [Web Console over HTTP](#web-console-over-http)
- [Migration order](#migration-order)

## The three TLS surfaces

1. **Client-to-cluster** — SDK connections and REST API calls from clients. Governed by the cluster's certificates plus the minimum TLS version and cipher-suite settings.
2. **Node-to-node** — internal cluster traffic (cluster management, replication, service traffic). Governed by node-to-node encryption plus the cluster encryption level.
3. **XDCR** — replication traffic between clusters, configured per remote-cluster reference.

All three should be encrypted in production.

## Minimum TLS version

Configured cluster-wide. Couchbase Server 7.6 and later **do not support TLS 1.0 or TLS 1.1** — those were deprecated in 7.2 and removed in 7.6. The only accepted values on a supported release are:

| Value | Notes |
|---|---|
| `tlsv1.2` | Default |
| `tlsv1.3` | Set this if every client SDK and tool in your estate supports TLS 1.3 |

```bash
couchbase-cli setting-security -c <host> -u <admin> -p <password> \
  --set --tls-min-version tlsv1.3
```

Read back the current values with `couchbase-cli setting-security --get`. The equivalent REST surface is `/settings/security`.

On clusters still running 7.0 or 7.1, `tlsv1` and `tlsv1.1` may still be selectable — explicitly set the minimum to `tlsv1.2` there.

## Cipher suites

Cipher suites are configured per service as an ordered preference list.

```bash
couchbase-cli setting-security -c <host> -u <admin> -p <password> \
  --set --cipher-suites <comma-separated-list> --tls-honor-cipher-order 1
```

**Couchbase Server accepts only IETF RFC cipher-suite names — OpenSSL names are rejected.** For example, use the RFC spelling `TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384`, not the OpenSSL spelling.

Guidance rather than a documented default: leave the shipped list alone unless a compliance standard forces a narrower set. An over-narrow list is the most common cause of "clients can no longer connect after hardening."

`--tls-honor-cipher-order 1` makes the server's preference order win over the client's.

## Cluster encryption level (node-to-node)

Node-to-node encryption is turned on per node (it requires the node to be addressed by the same address family the cluster uses), and the *level* is then set cluster-wide:

```bash
couchbase-cli setting-security -c <host> -u <admin> -p <password> \
  --set --cluster-encryption-level strict
```

| Level | Meaning |
|---|---|
| `control` | Server-management information passed between nodes is encrypted |
| `all` | All information passed between nodes, including service data, is encrypted |
| `strict` | `all`, plus only encrypted communication is permitted between nodes **and** between the cluster and external clients — the non-TLS ports stop accepting connections |

Loopback communication (`127.0.0.1`, `::1`) is still permitted unencrypted under `strict`.

**8.0+ only:** when node-to-node encryption is enabled, inter-node communication uses **mutual TLS** rather than basic authentication. On 7.x, node-to-node traffic under the same levels is TLS-encrypted but authenticated with credentials.

**Warning:** `strict` breaks every client that is not already connecting over TLS, immediately. Migrate clients first (see [Migration order](#migration-order)).

## Certificates

By default Couchbase Server generates a **self-signed root CA** at cluster creation and uses it to sign a node certificate for each node automatically. The CA appears in the Web Console under **Trusted Root Certificates**.

Points that matter in production:

- You **cannot** use the private key of the auto-generated self-signed root CA to sign anything yourself. To issue client certificates or XDCR certificates you must add your own CA to the trust store.
- If you remove the default self-signed CA, Couchbase Server stops auto-generating certificates for newly added nodes — you must place a node certificate before adding each node.
- Node certificates need a SAN covering the address clients actually use (hostname and/or IP).
- Certificate expiry monitoring is essential; an expired node certificate takes every TLS connection down at once. Set an expiry deliberately — it is what forces rotation to happen.

Rotation is performed by uploading the new CA to the cluster's trust store, then reloading each node's certificate. Adding a new trusted CA alongside the old one lets you roll node certificates one at a time with no connection loss. See the Couchbase certificate-rotation documentation for the exact procedure on your release — the REST paths have changed across 7.x and 8.0, so follow the docs for your version rather than a memorised endpoint.

## Client certificate authentication (mTLS)

Client certificate handling is off by default. It can be set to optional or mandatory, and you configure which certificate field (for example CN, or a SAN component) maps to a Couchbase username, plus how to extract the username from it.

**8.0+ only** adds two behaviours worth knowing:

- **Hybrid mode** — clients may authenticate with *either* a certificate or username/password, while inter-node communication still requires mTLS.
- **Mandatory certificate authentication combined with node-to-node encryption** enforces mTLS across all client-to-cluster communication as well.

SDK-side configuration (client certificate and key) belongs in `couchbase-app-integration`.

## Web Console over HTTP

Disable plaintext access to the Web Console and management REST API:

```bash
couchbase-cli setting-security -c <host> -u <admin> -p <password> \
  --set --disable-http-ui 1
```

Related hardening flags on the same command: `--disable-www-authenticate` (suppresses the browser basic-auth prompt), and the HSTS controls `--hsts-max-age`, `--hsts-include-sub-domains-enabled`, `--hsts-preload-enabled`.

## Migration order

Doing this in the wrong order causes an outage. The safe sequence:

1. Install and trust the CA on every client and tool.
2. Move all SDK clients to `couchbases://` and confirm zero traffic remains on the plaintext ports.
3. Raise the minimum TLS version.
4. Enable node-to-node encryption and set the level to `control`, then `all`.
5. Only once steps 2–4 are clean, set the cluster encryption level to `strict`.
6. Disable the Web Console over HTTP.
