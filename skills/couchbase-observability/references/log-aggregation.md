# Log aggregation

## Contents

- [Where the logs are](#where-the-logs-are)
- [The log files that matter](#the-log-files-that-matter)
- [Rotation, and what changed in 8.0](#rotation-and-what-changed-in-80)
- [Designing the shipping configuration](#designing-the-shipping-configuration)
- [Couchbase's own integrations](#couchbases-own-integrations)
- [Log patterns worth alerting on](#log-patterns-worth-alerting-on)
- [Collecting logs for a support ticket](#collecting-logs-for-a-support-ticket)

## Where the logs are

The default log directory on Linux is:

```
/opt/couchbase/var/lib/couchbase/logs
```

This is a frequent source of broken shipper configuration: `/var/lib/couchbase/logs` — without the `/opt/couchbase` prefix — is wrong on a standard Linux install. Confirm the path on the node rather than assuming, since the install prefix can differ, and it differs again on Windows and macOS.

In a container or under the Kubernetes operator, the same directory is inside the pod, typically reached through the mounted logs volume.

## The log files that matter

Couchbase writes a large number of log files. The ones worth shipping for operational monitoring:

| File | Contains |
|---|---|
| `error.log` | Errors across the cluster manager and services — the highest-value single file |
| `info.log` | General cluster manager activity |
| `debug.log` | Verbose cluster manager detail; ship only while investigating |
| `memcached.log` | Data service engine |
| `couchdb.log` | Data service persistence layer |
| `query.log` | Query Service |
| `indexer.log`, `projector.log` | Index Service |
| `fts.log` | Search Service |
| `eventing.log` | Eventing Service |
| `goxdcr.log` | XDCR |
| `analytics_error.log`, `analytics_warn.log`, `analytics_info.log` | Analytics Service |
| `backup_service.log` | Backup Service |
| `babysitter.log` | Process supervision — where you find out a service crashed and was restarted |
| `http_access.log` | Management API access |
| `prometheus.log` | The bundled metrics component |
| `audit.log` | Security audit events; see `couchbase-security-hardening/references/audit-logging.md` |

Note the names: it is `goxdcr.log`, not `xdcr.log`, and `indexer.log`, not `index.log`. There are also `rebalance/` and `reports/` subdirectories holding rebalance reports and crash reports.

`babysitter.log` is the file most often missing from a shipping configuration and the one that answers "did the process die, or did it hang?"

Ship `audit.log` through the security pipeline with its own retention, not through the general operational pipeline. It is evidence, and it has different handling requirements.

## Rotation, and what changed in 8.0

Couchbase rotates its logs itself.

**On 7.x**, `audit.log` was a regular file that was renamed on rotation. **In 8.0, `audit.log` is a symbolic link to the file currently being written.** A shipper configured to follow the inode of `audit.log` will therefore behave differently across the two releases. Configure the shipper to glob the directory and follow the rotated files, and verify the behaviour explicitly after an 8.0 upgrade — silent audit-shipping loss is the worst kind.

Rotated audit files carry the node name and a timestamp in the filename, so a fixed-filename match will not find them.

## Designing the shipping configuration

Any log shipper works — these are plain files. The design is the same whichever you use, and it is the design, not the tool version, that matters:

- **Run a collector on every node.** Each node logs only its own activity. Under Kubernetes this is a DaemonSet or a sidecar with the logs volume mounted.
- **Tag every record** with cluster name, node identity and service. Without these you cannot reconstruct anything cluster-wide, and the whole exercise is wasted.
- **Parse `audit.log` as JSON.** It is line-delimited JSON. Every other Couchbase log is semi-structured text.
- **Configure multiline handling** for the text logs. Erlang and Go stack traces span many lines, and a shipper that splits them turns one useful event into fifty useless ones.
- **Glob for rotated files**, do not follow a single fixed name.
- **Budget for volume.** `debug.log` in particular is large. Ship it selectively, or only during an investigation.

Deliberately no version numbers or pinned configurations here: pin your shipper version in your own infrastructure repository, where it can be upgraded on your schedule, rather than in a Couchbase runbook that will be stale within a release.

## Couchbase's own integrations

**Native Prometheus metrics** — for numeric monitoring, Couchbase Server 7.0+ exposes `/metrics` directly. See `prometheus-grafana.md`. Do not build a log-parsing pipeline to recover something already available as a metric.

**CMOS (Couchbase Monitoring and Observability Stack)** — Couchbase's packaged Prometheus/Grafana/cluster-monitor bundle. It is a **Developer Preview**, documented as not intended for production use and carrying no official support. Useful as a reference for default configuration; not a production answer.

**Couchbase Kubernetes (Autonomous) Operator** — see `couchbase-kubernetes` for collecting logs from pods.

**Third-party platforms** — Splunk (a Couchbase add-on with field extractions is published on Splunkbase), Elastic, and the major hosted observability vendors all have Couchbase integrations of varying currency. Check what the integration actually parses against your release before trusting its dashboards; several of them were built against pre-7.6 statistic names.

## Log patterns worth alerting on

Log-based alerting complements metric alerting; it does not replace it. These are patterns, not thresholds, and the severity column is operational judgement rather than anything Couchbase publishes.

| Pattern | Where | Why it matters |
|---|---|---|
| Process exit / restart entries | `babysitter.log` | A service crashed. Metrics may look fine after the restart |
| `FATAL` | any | Process about to terminate |
| Rebalance failure entries | `error.log`, `rebalance/` reports | A rebalance stopped partway; the cluster is in a mixed state |
| Failover entries | `error.log`, `info.log` | A node left the cluster, planned or not |
| Out-of-memory entries | `memcached.log` | Data service memory exhausted |
| Connection failures to a remote cluster | `goxdcr.log` | XDCR connectivity broken; the backlog metric will follow |
| Repeated `login failure` (event ID 8193) | `audit.log` | Credential stuffing or a broken service account |
| Certificate errors | `error.log`, `http_access.log` | Expiring or untrusted certificates, usually just before an outage |

Match on stable substrings, and re-verify the patterns after a version upgrade — log message wording is not a stable interface, unlike audit event IDs.

## Collecting logs for a support ticket

For a Couchbase support case, use `cbcollect_info` on each affected node rather than assembling files by hand. It gathers the logs, configuration and diagnostics that support expects, in the layout they expect. It is also worth running proactively at the start of a serious incident, before rotation ages out the evidence.
