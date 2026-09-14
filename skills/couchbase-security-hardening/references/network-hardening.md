# Network hardening

## Contents

- [Port reference](#port-reference)
- [Firewall rule design](#firewall-rule-design)
- [Restricting the Web Console](#restricting-the-web-console)
- [Network isolation on Capella](#network-isolation-on-capella)
- [Reviewing rules](#reviewing-rules)

## Port reference

Couchbase follows a consistent convention: the plaintext port has an encrypted counterpart, usually the same number plus 10000. Verify against the ports reference for your release before writing firewall rules — most, though not all, port numbers can be remapped at install time, so a hardened estate may not use the defaults at all.

### Client to cluster

| Plaintext | TLS | Service |
|---|---|---|
| 8091 | 18091 | Cluster management REST API and Web Console |
| 8092 | 18092 | Views (CAPI) |
| 8093 | 18093 | Query Service (SQL++) |
| 8094 | 18094 | Search Service |
| 8095 | 18095 | Analytics Service |
| 8096 | 18096 | Eventing Service |
| 8097 | 18097 | Backup Service |
| 9102 | 19102 | Index Service (GSI) scan |
| 11210 | 11207 | Data Service (KV) — the port SDKs use |

In production, allow only the TLS column from the application tier, and set the cluster encryption level to `strict` so the plaintext ports stop accepting connections (see `tls.md`).

### Node to node

Every node must reach every other node. In addition to the service ports above:

| Port | Purpose |
|---|---|
| 4369 | Erlang Port Mapper Daemon (EPMD) — node discovery |
| 11209 / 11206 | Data Service control commands (bucket and vBucket creation) |
| 21100 / 21150 | Cluster management, node-to-node (plaintext / TLS) |
| 9100–9105, 9110–9122, 9130 | Index and Analytics service internal traffic |

Ports in the 21200 / 21250 and 21300 / 21350 ranges are node-local only and should never be reachable from another host.

Confine all of this to the cluster's own private subnet or security group. None of it belongs on a path reachable from the application tier, let alone the internet.

### XDCR between clusters

| Port | Purpose |
|---|---|
| 18091 | Management API, for setting up and maintaining the remote-cluster reference |
| 11207 | Replication data |

For XDCR crossing any network you do not fully control, use the TLS ports and configure the remote-cluster reference for full certificate verification.

## Firewall rule design

Written as security-group logic; the same shape applies to host firewalls and network policies.

**Inbound, from the application tier:**
```
Allow TCP 11207 from app-sg          # KV — what the SDK actually uses
Allow TCP 18093 from app-sg          # Query, if the app runs SQL++
Allow TCP 18094 from app-sg          # Search, if the app uses it
Allow TCP 18091 from app-sg          # Management — only if the SDK bootstraps over HTTP
Deny all other inbound
```

Grant the service ports the application genuinely uses. An application that only does key-value work does not need the Query port.

**Inbound, intra-cluster:**
```
Allow TCP from cluster-sg to cluster-sg on the node-to-node ports above
```
Enumerate the ports if your tooling makes that maintainable. A blanket intra-cluster allow is common and defensible, but it is a finding in stricter regimes, so know which one you are in.

**Inbound, from operators:**
```
Allow TCP 18091 from bastion-sg or vpn-sg
```
Application servers do not need the Web Console.

**Outbound from cluster nodes:**
```
Allow to cluster-sg                  # intra-cluster
Allow TCP 18091, 11207 to remote-cluster-sg   # XDCR, if configured
Allow to the KMIP or KMS endpoint    # if using external key management
Allow to the LDAP server (LDAPS)     # if using external auth
Allow to the SAML IdP metadata URL   # if using SAML and fetching metadata by URL
Allow to the log/metrics collector   # if agents push rather than get scraped
Deny all other outbound
```

Default-deny egress catches a surprising amount; it is also the rule most likely to break certificate revocation checking and NTP, so test it on staging.

## Restricting the Web Console

1. Restrict 18091 to operator networks only.
2. Disable the Console over plaintext HTTP (`couchbase-cli setting-security --set --disable-http-ui 1`).
3. Consider requiring VPN or a bastion rather than exposing the Console to a corporate LAN.
4. On 7.6+, the same security settings command exposes HSTS controls for the Console.

## Network isolation on Capella

1. **Allowed IP list.** Configure the cluster's allowed CIDRs to your application egress ranges, VPN exit addresses and bastion addresses. Never add `0.0.0.0/0` — not even temporarily, because temporary entries become permanent.
2. **Private connectivity.** Capella supports provider-native private connectivity so traffic never crosses the public internet. Availability depends on cloud provider and plan; check the Capella networking documentation for what your organisation has.
3. **App Services.** If you run Capella App Services, it has its own allowed-IP configuration, separate from the cluster's. Hardening the cluster does not harden App Services.

## Reviewing rules

Firewall rules and security groups accumulate stale entries the same way RBAC accumulates stale users. Review them on the same cadence as the RBAC audit in `rbac.md`, and specifically look for: allowances added "temporarily" for a migration, rules referencing decommissioned CIDRs, and any plaintext Couchbase port still reachable after the cluster moved to `strict`.
