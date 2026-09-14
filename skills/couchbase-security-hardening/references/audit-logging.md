# Audit logging

## Contents

- [What the audit subsystem records](#what-the-audit-subsystem-records)
- [Enabling and configuring auditing](#enabling-and-configuring-auditing)
- [Filterable vs non-filterable events](#filterable-vs-non-filterable-events)
- [Events worth confirming are on](#events-worth-confirming-are-on)
- [Audit record format](#audit-record-format)
- [Rotation, pruning and retention](#rotation-pruning-and-retention)
- [Shipping to a SIEM](#shipping-to-a-siem)
- [Auditing on Capella](#auditing-on-capella)

## What the audit subsystem records

Each node writes security-relevant events as newline-delimited JSON to `audit.log` in its log directory. Events are grouped by the component that emits them — REST API / Cluster Manager, Data Service, Query and Index Service, Search, Eventing, Analytics, XDCR, View Engine, and the audit daemon itself.

Every event has a stable **numeric ID**. IDs, not names, are what you supply to the configuration API, and IDs are what you should key SIEM rules on — event display names are human-facing text.

Always check the audit event reference for your release before writing a filter list; events are added between releases.

## Enabling and configuring auditing

```bash
couchbase-cli setting-audit -c <host> -u <admin> -p <password> \
  --set \
  --audit-enabled 1 \
  --audit-log-path /opt/couchbase/var/lib/couchbase/logs \
  --audit-log-rotate-interval 86400 \
  --audit-log-rotate-size 104857600 \
  --prune-age 2592000
```

| Flag | Meaning |
|---|---|
| `--audit-enabled` | Master switch |
| `--audit-log-path` | Directory for `audit.log`; defaults to the node's log directory |
| `--audit-log-rotate-interval` | Seconds between rotations |
| `--audit-log-rotate-size` | Rotate when the file exceeds this many bytes |
| `--prune-age` | Age in seconds after which rotated audit logs are deleted; omit to keep them |
| `--disabled-users` | Users whose filterable events are not recorded |
| `--disable-events` | Comma-separated list of filterable event **IDs** to suppress |

Inspect the current state with `--get-settings`, and enumerate what can actually be filtered on this cluster with `--list-filterable-events`. The REST equivalent is `/settings/audit`.

**On `--disabled-users` and `--disable-events`:** these are throughput escape hatches, not security controls. Their legitimate use is a very high-frequency service identity whose document-level events would swamp the pipeline. Never use them to make an identity's administrative actions invisible — and note that they cannot, because administrative events are non-filterable.

`--prune-age` deletes logs on the node. Only set it once shipping to an external system is confirmed working, or you are deleting your own evidence.

## Filterable vs non-filterable events

This distinction is the single most misunderstood part of Couchbase auditing:

- **Non-filterable events are always recorded** once auditing is enabled. They cannot be turned off, and there is nothing to "enable" for them. Almost every administrative and security event is in this category — logins, user and group changes, bucket lifecycle, failover, rebalance, certificate operations, LDAP changes, password-policy changes, audit-daemon reconfiguration, all XDCR replication lifecycle events.
- **Filterable events** can be disabled individually or per user. These are the high-volume data-plane events — document reads and mutations, SQL++ statements, view queries.

So a compliance checklist item reading "enable the admin login audit event" is a no-op: enabling auditing at all is what turns it on. The real checklist item is "confirm the *filterable* data-access events we need are not disabled."

## Events worth confirming are on

A representative set, with IDs from the current audit event reference. Verify these IDs against the reference for your release.

| ID | Event | Group | Filterable |
|---|---|---|---|
| 8192 | login success | REST API | No |
| 8193 | login failure | REST API | No |
| 8232 | set user | REST API | No |
| 8194 | delete user | REST API | No |
| 8195 | user credentials change | REST API | No |
| 8210 / 8212 / 8211 | add / update / delete group | REST API | No |
| 8201 / 8202 / 8203 / 8204 | create / modify / delete / flush bucket | REST API | No |
| 8198 | failover nodes | REST API | No |
| 8200 | rebalance initiated | REST API | No |
| 8226 / 8230 | regenerate certificate / reload node certificate | REST API | No |
| 8227 / 8246 | setup LDAP / modify LDAP settings | REST API | No |
| 8233 / 8234 | master password change / encryption key rotation | REST API | No |
| 8235 | password policy | REST API | No |
| 8240 | configured audit daemon | REST API | No |
| 16387 / 16390 | XDCR replication creation / cancellation | XDCR | No |
| 20488 | document read | Data Service | **Yes** |
| 20490 | document modify | Data Service | **Yes** |
| 20491 | document delete | Data Service | **Yes** |
| 20492 | select bucket | Data Service | **Yes** |
| 28672 | SELECT statement | Query and Index Service | **Yes** |
| 28685 / 28686 | GRANT ROLE / REVOKE ROLE statement | Query and Index Service | **Yes** |

Operational judgement, not a documented default: turn on the Data Service document events (20488–20492) only for the clusters that hold regulated data, and turn on `SELECT statement` (28672) only where your framework explicitly requires query-text capture — it is the highest-volume filterable event Couchbase emits, and it can put query text containing predicates on personal data into the log.

## Audit record format

One JSON object per line. Fields you can rely on:

| Field | Meaning |
|---|---|
| `id` | Numeric event ID |
| `name` | Human-readable event name |
| `description` | Longer description |
| `timestamp` | UTC, W3C format |
| `real_userid` | `{ "domain": ..., "user": ... }`; domain is `local`, `external`, `builtin` or `rejected` |
| `local` | IP and port of the node that processed the request |
| `remote` | IP and port the request came from |

Additional fields vary by event. Data-service events identify the document key; they do not record the document body, so audit logs do not themselves become a copy of your regulated data.

Key SIEM rules on `id`. Do not key them on `name` or `description`, which are display text.

## Rotation, pruning and retention

Rotated files are renamed with the node name and a timestamp (for example `<node>-2026-07-30T15-42-18-audit.log`), so a shipper must glob the directory rather than follow a single fixed filename.

Couchbase does not implement long-term retention. Decide retention in the destination system and set `--prune-age` on the node to something just long enough to ride out a shipping outage.

**On-node risk:** audit logs on a compromised node are evidence an attacker can destroy. Ship them off the node promptly, and keep the log directory writable only by the Couchbase service account.

## Shipping to a SIEM

Audit records are line-delimited JSON on the local filesystem, so any log shipper works. Whichever you use, the shape of the configuration is the same:

- Tail `audit.log` **and** the rotated `*-audit.log` files in the audit log directory.
- Parse each line as JSON rather than treating it as free text.
- Tag every record with the cluster name and the node identity — each node audits only its own activity, so records must be aggregated across all nodes to reconstruct a session.
- Ship from every node, including nodes that run no data service.

This applies equally to Filebeat/Elastic, Fluent Bit/Fluentd, Splunk forwarders (a Couchbase add-on providing field extractions is published on Splunkbase), and the log agents of hosted observability vendors. Deliberately no version numbers here: pin shipper versions in your own infrastructure repo, not in a Couchbase runbook.

Alerting: a burst of `login failure` (8193) from one source, any `set user` (8232) or group change outside a change window, and any `encryption key rotation` (8234) or `password policy` (8235) change nobody scheduled are all worth a page.

## Auditing on Capella

On Capella, the audit subsystem is operated by Couchbase and you have no filesystem access to the nodes. Event content is the same. Configuration of which events are captured, and forwarding of audit data to your own systems, are done through the Capella interface and its log-forwarding integrations; availability depends on your Capella plan. Check the Capella documentation for what your organisation's plan includes rather than assuming parity with self-managed.
