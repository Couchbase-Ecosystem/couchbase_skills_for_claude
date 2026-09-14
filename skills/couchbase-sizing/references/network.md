# Network and XDCR bandwidth

Network is often invisible in sizing until something breaks. Couchbase clusters move a lot of bytes — replicas, indexing, rebalances, XDCR, query results — and under-provisioned network shows up as confusing latency spikes that are hard to diagnose.

> **Couchbase publishes no per-workload network specification.** The bandwidth *equations* below are arithmetic on your own write rate and document size, and are safe. The recommended link speeds and the rebalance multipliers are field heuristics, labelled *(estimate)*. Cross-AZ and egress charges exist on every cloud, but this reference quotes **no rates or costs** — check your provider's current pricing yourself.

## Contents

- [Network within the cluster](#network-within-the-cluster)
- [XDCR bandwidth](#xdcr-bandwidth)
- [Network for client traffic](#network-for-client-traffic)
- [Network during rebalance](#network-during-rebalance)
- [Multi-region / multi-cluster considerations](#multi-region--multi-cluster-considerations)
- [Application-level network optimizations](#application-level-network-optimizations)
- [Network monitoring signals](#network-monitoring-signals)
- [Cloud-specific gotchas](#cloud-specific-gotchas)
- [Quick decision tree](#quick-decision-tree)

## Network within the cluster

Couchbase nodes talk constantly:

- **Replication traffic**: every write propagates to replicas. Bandwidth = `write_rate × avg_doc_size × replica_count`
- **Rebalance traffic**: data movement during topology changes. Can spike to many GB/sec briefly
- **Query traffic**: query results streaming between Query and Data nodes
- **Index traffic**: index service pulls mutations from Data service
- **Eventing traffic**: similar — mutations push to Eventing
- **Cluster manager traffic**: heartbeats, stats, config sync. Minimal

For a typical production cluster, internal network *(estimate)*:
- **10 Gbps** is a reasonable floor (1 Gbps works for small clusters but limits rebalance speed noticeably)
- **25 Gbps+** for high-write workloads or large clusters

These are starting points. The equations below give you the actual steady-state requirement for *your* workload — compute it and compare.

Cloud VMs: pick instance types with the higher network tiers. AWS for example has "Up to X Gbps" labels — the actual sustained throughput is often lower; benchmark for your workload.

### Worked example

Inputs:
- 50,000 writes/sec sustained
- Average doc size: 2 KB
- Replica count: 2 (so each write goes to 2 other nodes)

```
write_bandwidth_per_write = 2 KB × 2 replicas = 4 KB
total_replication_traffic = 50,000 × 4 KB = 200 MB/sec = 1.6 Gbps
```

This is the steady-state, and the arithmetic is exact for your inputs. Rebalance adds substantially on top — Couchbase publishes no multiplier for it, and the real figure depends on how much data moves, disk speed and rebalance throttling settings, so **measure a rebalance in staging at realistic data volume** rather than applying a factor. What the arithmetic already tells you: 10 Gbps carries this steady-state with room; 1 Gbps would be saturated before rebalance is even considered.

## XDCR bandwidth

XDCR (cross-datacenter replication) sends data over WAN/inter-region links — typically slower and more expensive than intra-cluster network.

```
xdcr_bandwidth = source_write_rate × source_avg_doc_size × replication_factor
```

Where `replication_factor` is usually 1 (one target cluster) but can be higher with multiple target clusters.

### Worked example

Same inputs as above + an XDCR replication to a second cluster:

```
xdcr_traffic = 50,000 × 2 KB × 1 = 100 MB/sec = 800 Mbps
```

800 Mbps continuous WAN bandwidth. Whether this is feasible depends on your inter-region link:

Link capacities vary by provider, region pair and contract, so the table below is orientation *(estimate)* — get the actual figure for your link and compare it against the computed requirement above:

| Link type | Typical order of magnitude *(estimate)* | XDCR feasibility |
|---|---|---|
| Cloud inter-region, same provider | Gbps range | Handles most workloads |
| Cloud inter-region, cross-provider | Varies widely | Plan carefully; measure |
| VPN over public internet | Sub-Gbps | Limits XDCR to lower write rates |
| Dedicated leased line | Gbps range | Good for most workloads |
| Branch / edge sites | Often well under 100 Mbps | XDCR may be infeasible |

XDCR has built-in throttling, but if the source writes faster than the link can replicate, lag accumulates indefinitely — the throttle protects the link, not your consistency window.

**Related XDCR sizing considerations:**
- The conflict-resolution policy is chosen at **bucket creation** and cannot be changed afterwards. The default is **sequence-number-based**; timestamp-based (LWW) must be selected explicitly and requires NTP-synchronized clocks across all participating clusters
- Couchbase Server **8.0** adds XDCR **Conflict Logging** and an **Incoming Replications** view, plus ships the **xdcrDiffer** diagnostic utility in the installation package — useful for quantifying conflict rate and divergence in an active-active deployment

### XDCR initial sync

The first sync replicates the entire dataset. The theoretical floor is `dataset_size / link_bandwidth`; real throughput is below line rate, so treat the theoretical figure as a lower bound and measure. For 1 TB over a 1 Gbps link, the theoretical floor alone is several hours.

Plan accordingly:
- Start the XDCR setup during off-peak hours
- Monitor replication progress (`changes_left` and the replication statistics) throughout
- Don't put production traffic on the target until initial sync completes

## Network for client traffic

In addition to internal traffic, the cluster receives client traffic (KV gets/puts, queries, etc.).

```
client_ingress = peak_client_qps × avg_request_size
client_egress = peak_client_qps × avg_response_size
```

For a typical web app with 50K QPS:
- Avg request: 200 bytes → 10 MB/sec (small)
- Avg response: 5 KB (small JSON doc) → 250 MB/sec = 2 Gbps

Egress dominates. For workloads returning large query results or full documents, plan egress as the constraint.

## Network during rebalance

Rebalances move data between nodes. The network impact:

Rebalance traffic is additive to normal cluster traffic, and its rate depends on data volume, disk throughput, CPU and the cluster's rebalance settings. **Couchbase publishes no per-minute movement rate, and the figures that circulate are not reliable** — measure a rebalance in staging at realistic data volume and record how long it takes and what it costs the network.

What you can plan on without a number: internal network needs headroom beyond steady state. If you provision exactly enough for steady-state, rebalances will be slow — backpressure throttles them — but they will also visibly impact normal operations while they run.

## Multi-region / multi-cluster considerations

If you operate clusters in multiple regions:

- **Active-active XDCR**: bidirectional replication. Network bandwidth doubles (both directions). Conflict resolution becomes important — see `couchbase-mcp` skill's reference on XDCR conflict logging
- **Active-passive XDCR**: writes go to one cluster, replicate to the other read-only. Simpler, less network
- **Geo-distributed reads with regional writes**: route reads to the local cluster, writes to the regional master cluster, replicate via XDCR. Most common pattern

The further apart the clusters, the more important to monitor XDCR lag. Replication lag at 10 seconds is fine; at 10 minutes there's something to investigate.

## Application-level network optimizations

Things the user can do to reduce required network:

- **Use sub-document `lookup_in` to fetch only specific fields** instead of full documents — drops bandwidth proportional to the fraction of fields not retrieved. Maximum 16 operations per request
- **Use your SDK's multi-operations, or bounded concurrency**, instead of N sequential round-trips
- **Project only the fields you need in SQL++** — `SELECT *` over wide documents is the most common egress surprise
- **Avoid large response sets**: paginate, and prefer keyset pagination over deep `OFFSET`
- **Check your SDK's compression support** — the SDKs support compression of document bodies; confirm what your pinned version does before assuming it's on

## Network monitoring signals

Symptoms of network bottlenecks:

- Replicas falling behind (a growing replication queue length)
- XDCR lag growing (`changes_left` trending upward)
- Increased query latency p99 with no obvious CPU or disk issue
- Rebalance taking much longer than estimated
- Client-side timeouts that don't correlate with cluster CPU/memory pressure

If you see these together, suspect network. Confirm with infrastructure-level monitoring (interface utilization, packet drops).

## Cloud-specific gotchas

- **Burst vs sustained bandwidth**: many cloud instance types advertise a peak that is only sustained for a limited period. Sustained Couchbase workloads need instance types with a documented *sustained* figure, not a burst one. This is a capacity trap, and it is the one that actually breaks clusters
- **Cross-AZ and internet egress are metered** on every major cloud. Multi-AZ clusters generate continuous cross-AZ replication traffic by design. Check your provider's current rates yourself — this reference deliberately quotes none — and factor the volume (which the equations above give you) into whatever that conversation is
- **Co-locate clients with the cluster** where you can: it reduces both latency and metered egress
- **NAT gateway bandwidth limits**: traffic through a NAT gateway can be capped; keep cluster-internal traffic off it

## Quick decision tree

- **Calculating cluster-internal bandwidth?** `write_rate × avg_doc_size × replica_count` + headroom for rebalance
- **Calculating XDCR bandwidth?** `source_write_rate × source_avg_doc_size × target_count`
- **Initial XDCR sync time?** `total_dataset_size / link_bandwidth` is the floor; real throughput is below line rate, so measure
- **Cluster-internal network spec?** *(estimate)* 10 Gbps as a floor for production, 25 Gbps+ for write-heavy or large clusters — but compute the steady-state requirement from your own write rate first
- **Rebalance impact?** Measure it in staging at realistic data volume. Don't apply a multiplier
- **Multi-AZ deployment in cloud?** Cross-AZ replication traffic is continuous and metered; compute the volume here and take the rates from your provider
- **WAN-bandwidth-constrained for XDCR?** Filter replications to only the buckets and collections that need to cross; prefer one-way active-passive over bidirectional
