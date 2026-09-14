# System-level tuning

## Contents

- [Connection limits](#connection-limits)
- [OS-level settings Couchbase documents](#os-level-settings-couchbase-documents)
- [OS settings Couchbase does not publish values for](#os-settings-couchbase-does-not-publish-values-for)
- [Service memory quotas](#service-memory-quotas)
- [Rebalance performance](#rebalance-performance)
- [Multi-service node contention](#multi-service-node-contention)

## Connection limits

The Data service accepts key-value connections on port 11207 (TLS) and port 11210 (non-TLS). Each connection consumes a file descriptor and some memory.

**The documented hard limit is 60,000 maximum concurrent key-value connections per Data node**, counted across both ports together. Memcached and system-user connections are separately administrator-defined.

Two cluster-wide settings govern this:

- `max_connections` — the maximum number of connections memcached will accept for the cluster
- `system_connections` — the maximum number of connections from authenticated system users

Couchbase does not publish default values for either setting, so **read the current values off your cluster rather than assuming one**. Values that are too large are rejected with `400 Bad Request` and a `too_large` message.

Signs you are hitting connection limits:
- SDK connection attempts fail under load while existing connections keep working
- `curr_connections` per node sits near the configured maximum
- Connection errors appear in SDK logs specifically during traffic peaks

**How to check:**
```python
admin_stats_single(metric="kv_curr_connections", cluster="prod")
# Or admin_stats_multi / admin_stats_bucket for several metrics in one call.
# Look at curr_connections per node, and compare against the configured maximum
```

**Fixes, in the order worth trying:**

1. **Reduce connections per client.** SDK connection pools sized far above what the application uses concurrently are the usual cause. An application instance holding hundreds of connections to each node is a design problem, not a capacity problem.
2. **Raise the cluster connection settings** if the nodes genuinely have the file descriptors and memory for it, staying under the 60,000 per-node ceiling. Neither MCP server exposes `max_connections` / `system_connections`; change them with `couchbase-cli setting-cluster`, the Management REST API (`/pools/default/settings/memcached/global`), or the Web Console.
3. **Raise the OS file descriptor limit** to match. Couchbase's own deployment guidance for VMs and containers uses `ulimit -n 40960` (`nofile`), alongside `ulimit -c unlimited` (core) and `ulimit -l unlimited` (memlock). For containers this is `--ulimit nofile=40960:40960`. If you raise the connection setting well above what 40960 descriptors supports, raise `nofile` correspondingly and verify with `ulimit -n` as the `couchbase` user.
4. **Add Data nodes.** Each additional Data node brings its own connection ceiling.

Sources: https://docs.couchbase.com/server/current/learn/clusters-and-availability/size-limitations.html, https://docs.couchbase.com/server/current/rest-api/rest-manage-cluster-connections.html and https://docs.couchbase.com/server/current/install/best-practices-vm.html

## OS-level settings Couchbase documents

These have published Couchbase recommendations and should be treated as requirements on production nodes.

### Transparent Huge Pages

"You must disable the THP memory management system on each node that runs Couchbase Server."

```bash
# Immediate
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo never > /sys/kernel/mm/transparent_hugepage/defrag
```

Make it persistent through a systemd unit or your configuration-management tooling so it survives reboot. Couchbase publishes a dedicated procedure page for this.

### Swappiness

"You need to set the swappiness setting to 0, or at most 1, for optimal Couchbase Server operation."

On Linux kernel 3.5-rc1 and later, **1** is the recommended value — kernel 3.5-rc1 changed behavior such that swappiness 0 raises OOM-kill risk. Use 0 only on older kernels.

```bash
# Immediate (until reboot)
sysctl -w vm.swappiness=1

# Permanent
echo "vm.swappiness=1" >> /etc/sysctl.conf
sysctl -p
```

Leaving the distro default (60) lets the OS page out Couchbase's working memory, which collapses latency.

### File system

"When deploying Couchbase Server on production Linux, you should use either the XFS or ext4 file system." On Windows, use 64k allocation sizes on NTFS.

Sources: https://docs.couchbase.com/server/current/install/install-production-deployment.html, https://docs.couchbase.com/server/current/install/install-swap-space.html and https://docs.couchbase.com/server/current/install/thp-disable.html

## OS settings Couchbase does not publish values for

> The items in this section are general Linux tuning, **not** Couchbase-published recommendations. Couchbase's deployment documentation does not specify values for them. Treat them as things to measure and validate on your own hardware, and do not cite specific numbers as Couchbase guidance.

**Network buffer sizes.** On clusters sustaining very high throughput — particularly XDCR and Analytics DCP feeds — the kernel socket buffer maximums (`net.core.rmem_max`, `net.core.wmem_max`, `net.ipv4.tcp_rmem`, `net.ipv4.tcp_wmem`) can become the constraint before the NIC does. Confirm with network-level metrics that buffers are actually the bottleneck before changing them.

**I/O scheduler.** On NVMe devices the multi-queue schedulers (`none`, `mq-deadline`) are the relevant choices; the legacy single-queue schedulers do not apply. Check the current setting and change it only if I/O latency data supports it:

```bash
cat /sys/block/<device>/queue/scheduler
```

**NUMA.** On multi-socket servers, memory access across NUMA nodes is slower than local access, which can show up as latency variance. Inspect the current topology and binding before assuming anything:

```bash
numactl --show
```

On Kubernetes, node affinity and topology-aware scheduling are the levers. Verify Couchbase's actual placement rather than assuming the platform handled it.

## Service memory quotas

Each service has its own memory quota, set cluster-wide:

```python
admin_cluster_memory_set(
    dataMemoryQuota=16384,      # MB - Data service
    indexMemoryQuota=8192,      # MB - GSI index RAM
    ftsMemoryQuota=4096,        # MB - Search Service index RAM
    eventingMemoryQuota=2048,   # MB - Eventing
    analyticsMemoryQuota=4096,  # MB - Analytics Service
    cluster="prod",
    confirm=True,
)
# admin_cluster_memory_set is annotated destructive: misconfigured quotas can crash
# services, and lowering a quota below the working set evicts.
```

**The common failure is leaving the Index service quota at its initial small value after building a real index set.** When the Index service exhausts its quota it pages index data to disk and query latency degrades sharply. Size the Index quota against the actual resident index footprint on Index nodes, leaving headroom for index growth and for the OS.

Couchbase does not publish a single correct ratio here. Measure the index RAM actually in use, then set the quota above it with headroom, and alert on approaching the quota rather than on exceeding it.

If the cluster is on 8.0 and you plan to build Hyperscale or Composite Vector indexes, budget Index Service RAM for them before the build — see `couchbase-upgrade`.

## Rebalance performance

Rebalance moves vBuckets between nodes and is I/O-heavy. On large datasets it can run for hours.

The concurrency lever is `rebalanceMovesPerNode`: the number of concurrent vBucket moves per node. It is documented as **defaulting to 4, with a valid range of 1 to 64 inclusive.**

Neither MCP server exposes `rebalanceMovesPerNode`; set it with `couchbase-cli setting-rebalance`, the Management REST API (`/settings/rebalance`), or the Web Console.

Raising it shortens rebalance at the cost of more concurrent I/O and more impact on live traffic; lowering it does the reverse. The right value depends on storage throughput and how much latency impact the workload tolerates, so change it in small steps and watch KV latency during the rebalance rather than jumping to the top of the range.

Monitor progress:
```python
admin_rebalance_progress(cluster="prod")
```

Source: https://docs.couchbase.com/server/current/rest-api/rest-limit-rebalance-moves.html

## Multi-service node contention

When Data, Index, Query, Search, Eventing or Analytics share a node, they compete for CPU, memory and disk I/O. Recurring patterns:

- **Index build vs KV writes** — both generate heavy sequential disk I/O. Schedule index builds outside peak write periods.
- **Query CPU vs Data service** — complex queries are CPU-intensive; a query-load spike on a shared node can starve the Data service.
- **Analytics DCP streaming vs KV** — Analytics ingests via DCP, adding read load on the Data service.
- **Compaction vs everything** — on Magma buckets compaction cannot be windowed, so it is always part of the background I/O budget.

The durable fix is service isolation: dedicated nodes per service (Multi-Dimensional Scaling). Where that is not possible, set service quotas conservatively, monitor per-service CPU via `admin_stats_multi`, and schedule the controllable heavy operations (index builds, backups, Couchstore compaction windows) away from each other.
