# Nodes and replicas

How many nodes do you need, what replica count, and where should each service live? The answers come from three constraints: fault tolerance, load capacity, and ops simplicity.

> **Documented values are cited; heuristics are labelled *(estimate)*.**

## Contents

- [Replica count](#replica-count)
- [Minimum node count for replicas](#minimum-node-count-for-replicas)
- [The N-1 sizing rule](#the-n-1-sizing-rule)
- [Scale up vs scale out](#scale-up-vs-scale-out)
- [Service placement](#service-placement)
- [Server groups (rack awareness)](#server-groups-rack-awareness)
- [Capella node count](#capella-node-count)
- [Quick decision tree](#quick-decision-tree)

## Replica count

Replica count is the number of additional copies of each piece of data, beyond the active copy.

| Replicas | Total copies | Total nodes data lives on | Survives | Use when |
|---|---|---|---|---|
| 0 | 1 | 1 | nothing | Dev / cache where data loss is OK |
| 1 | 2 | 2 | 1 node failure | Most production workloads |
| 2 | 3 | 3 | 2 node failures (rare) | Critical data, large clusters |
| 3 | 4 | 4 | 3 node failures (very rare) | Compliance / regulatory requirements |

The default is replica = 1. Replica = 2 is justified for:
- Compliance requiring N+2 durability
- Large clusters (>10 nodes) where simultaneous double-failures are statistically meaningful
- Data so critical that a single failure-during-rebalance can't be tolerated

Replica = 3 is rare; usually only seen in highly regulated environments.

**Cost of replicas:** each replica is a full copy of the data. RAM and disk multiply by `1 + replica_count` — the documented sizing formula carries this as `no_of_copies`. Network traffic also scales, since every write replicates.

**Replicas do not serve ordinary reads.** An ordinary `get` always goes to the active vBucket; replica reads are an explicit, separate SDK operation used during failover, and they can return stale data. Adding a replica to increase read throughput is a sizing mistake — replicas buy availability and durability, nothing else.

**Replicas interact with durability.** The `majority` durability level needs a majority of Data Service nodes to acknowledge the write. With replica=1 (2 copies), that means both — so a single node failure makes `majority` writes impossible until the cluster recovers. With replica=2 (3 copies), majority is 2, and the cluster tolerates one failure while still accepting durable writes. If durable writes must survive a node failure, replica=2 is the requirement, not a nicety.

## Minimum node count for replicas

Couchbase requires at least `1 + replica_count` data nodes to place all copies. Practical minimums (with one extra for failure tolerance):

| Replicas | Absolute min | Recommended min |
|---|---|---|
| 0 | 1 | 2 |
| 1 | 2 | **3** |
| 2 | 3 | **4** |
| 3 | 4 | **5** |

"Recommended" assumes you want to be able to LOSE one node and still have full replica placement.

3 data nodes with replica=1 is the most common starting production shape.

## The N-1 sizing rule

Always size for `N-1` nodes (one node missing). When a node fails:

- Its data load redistributes to remaining nodes
- Its replicas on other nodes are promoted to active
- The cluster needs to handle 100% of normal load with one less node

If your cluster runs at 80% capacity on N nodes, losing one means the remaining `N-1` nodes need to handle:
- 100% of the load (unchanged)
- Across N-1 nodes instead of N

So the per-node load goes from 80% to `80% × N / (N-1)`. For N=3: 120% — over capacity, you're degraded.

For sustainable failure tolerance, size for steady-state utilization no higher than `(N-1) / N × 80%`:

| Nodes | Steady-state max |
|---|---|
| 3 | ~53% |
| 4 | ~60% |
| 5 | ~64% |
| 6 | ~67% |
| 10 | ~72% |

This is why larger clusters can run "hotter" — losing one of 10 is less impactful than losing one of 3.

## Scale up vs scale out

Two ways to add capacity: bigger nodes (scale up) or more nodes (scale out).

| Dimension | Scale up favored | Scale out favored |
|---|---|---|
| Throughput-per-node | Yes | Lower per-node |
| Fault tolerance | Worse | Better |
| RAM utilization | Better at high tiers | More fragmentation |
| Rebalance time | Slower (more data per node) | Faster (less data per node) |
| Network blast radius on failure | Larger | Smaller |
| Infrastructure footprint | Fewer, larger instances | More, smaller instances |
| Operational complexity | Simpler (fewer machines) | More machines to monitor |

**Default progression:**
1. Start with smallest reasonable cluster (3 nodes typically)
2. Grow vertically (bigger nodes) until single-node failure becomes too impactful
3. Then grow horizontally (more nodes)
4. At very large scale (>20 nodes), consider whether multiple clusters with XDCR would simplify ops

**Documented limits:**
- **Capella: maximum 27 nodes per cluster**, minimum 3 nodes in a Data service group and 2 in any other service group
- **Maximum 30 buckets per cluster** ([Size Limits](https://docs.couchbase.com/server/current/learn/clusters-and-availability/size-limitations.html))
- **Maximum 60,000 concurrent key-value connections**

Couchbase Server does not publish a hard maximum node count for self-managed clusters. **Don't quote one.** What is true is that coordination overhead, rebalance duration and blast radius all grow with cluster size, so past a few dozen nodes the question shifts from "can it" to "should this be two clusters with XDCR." Likewise there is no documented per-node RAM ceiling — very large nodes are limited in practice by rebalance time and failure blast radius, not by a published number.

## Service placement

Couchbase has multiple services that can run on any node combination. Choosing well materially affects cost and performance.

### Service list

- **Data (KV)** — required; the heart of Couchbase. In Capella it is mandatory and cannot be removed
- **Query** — required if you want SQL++ queries
- **Index (GSI)** — required if you want secondary indexes
- **Search** — the Search Service: full-text and, from 8.0, Search vector indexes ("FTS" is the older name for it)
- **Eventing** — server-side JavaScript functions reacting to data mutations
- **Analytics** — the in-cluster analytics service for OLAP-style workloads. Distinct from Capella Analytics / Couchbase Enterprise Analytics, which are separate products
- **Backup** — coordinator for backup/restore operations

**Documented minimum memory quotas** ([Memory](https://docs.couchbase.com/server/current/learn/buckets-memory-and-storage/memory.html)): Data 256 MB, Index 256 MB, Search 256 MB, Eventing 256 MB, Analytics 1024 MB. Couchbase also recommends allocating **no more than 90% of a node's memory** across all services (80% on small-memory nodes), and budgeting **0.2 CPU cores per bucket** per node.

Couchbase Server **8.0** allows the Index, Query, Search, Analytics, Eventing and Backup services to be added to and removed from a node dynamically, without a node add/remove cycle — which makes service placement considerably cheaper to change after the fact than it was on 7.x.

### Three deployment patterns

**Pattern A: all services on every node**

Simplest. All N nodes run Data, Query, Index, Search, Eventing.

Good for: small clusters (≤ 5 nodes), dev/staging, low total scale.

Bad for: production at scale — services compete for RAM and CPU; one heavy query can starve KV operations. Note that every service on the node claims part of the ≤90% services budget, and each has its own documented minimum quota.

**Pattern B: Data nodes + Query/Index nodes**

Separate the data plane from the query plane. Typical: 3 data nodes + 2 query/index nodes.

Data nodes do KV only — low-latency, RAM-budgeted for working set.
Query/Index nodes run Query, Index, and possibly Search.

Good for: medium scale (5-15 nodes), production.

Most common production shape.

**Pattern C: dedicated nodes per service**

Each service has its own node pool. Data nodes are storage-optimized. Index nodes are RAM-optimized. Analytics nodes are storage + CPU optimized (often a completely different instance type).

Good for: large scale (>15 nodes), workload isolation requirements.

The most resource-intensive option, but the cleanest isolation.

### Service-specific sizing notes

**Data service:** dominant RAM consumer (see `memory.md`). Storage = total data × (1 + replicas).

**Query service:** RAM for query workspace (sorts, joins, aggregates). Stateless — just CPU and RAM. Scale horizontally to add throughput.

**Index service:** memory profile depends entirely on the **index storage mode** — standard (disk-optimized, the default, both editions) lets index size exceed node memory; memory-optimized (Enterprise Edition only) requires the quota to hold every resident index and stalls index maintenance at 95% of quota. See `indexes.md`. Stateful — losing an index node means rebuilding or re-syncing on recovery. Plan at least 2 index nodes for fault tolerance, and note Capella's 2-node minimum per non-Data service group.

**Search:** RAM-heavy when vector indexes are involved (`indexes.md`). Disk for the index data. Stateful like Index.

**Eventing:** memory scales with deployed functions and their worker counts, and Couchbase publishes no per-function figure — measure it in staging. 8.0's `num_nodes_running` setting controls how many nodes execute a given function per scope, which is a direct lever on the aggregate footprint. Often co-located with Data because functions react to mutations.

**Analytics:** a different resource profile from OLTP — it maintains its own copies of ingested data, so it is storage-heavy, and query memory scales with join and aggregation complexity. Minimum quota 1024 MB. Usually on its own node pool.

**Backup:** lightweight coordinator. Can run on any node; minimal resource needs.

## Server groups (rack awareness)

For multi-rack / multi-AZ deployments, server groups tell Couchbase to place replicas across groups. So if rack 1 fails, rack 2 has the replicas.

Configuration via `admin_server_group_*` tools.

Without server groups, Couchbase distributes replicas without rack awareness — a rack failure could lose multiple replica copies of the same data.

**Use server groups when:**
- AWS / GCP / Azure deployments across AZs
- On-prem with multiple racks/data centers
- Any deployment where node failures are correlated (entire rack power, network switch)

The rule: at least `1 + replica_count` server groups so replicas can be distributed.

## Capella node count

In Capella you define **service groups**: each one is a set of nodes running a specified set of services, with its own compute instance type (which determines vCPUs and memory per node) and disk configuration.

Documented constraints:

- **Minimum 3 nodes** in a Data service group; **minimum 2 nodes** in other service groups
- **Maximum 27 nodes per cluster**
- The **Data Service is mandatory** and cannot be removed
- **Single Node clusters cannot have additional service groups**, and scaling one out requires a minimum compute configuration of 4 vCPUs / 16 GB RAM
- Capella distributes each node's memory between the OS and all services deployed in that service group

The same fault-tolerance math applies: at least 3 nodes for replica=1, and validate the N-1 case.

## Quick decision tree

- **Replica count?** → 1 for most production. Choose 2 when compliance requires it, at large cluster sizes, **or when `majority` durable writes must keep working through a single node failure** — with replica=1 they can't
- **Minimum nodes?** → 3 for replica=1, 4 for replica=2, 5 for replica=3
- **Steady-state load target?** → never above `(N-1)/N × 80%` so a single node failure is absorbable
- **Scale up vs out?** → scale up while N is small; scale out when single-node failure becomes too impactful
- **Service mix?** → all-services on small clusters; data + query/index split at medium scale; dedicated per-service at large scale
- **Multi-AZ / multi-rack?** → configure server groups so replicas distribute correctly
- **Analytics needed?** → establish whether it's the in-cluster Analytics Service or Capella Analytics / Couchbase Enterprise Analytics first; run the in-cluster service on its own node pool
- **Want to "add replicas to scale reads"?** → that isn't how it works. Ordinary reads always go to the active copy. Scale reads with more nodes or more Query capacity, not more replicas
- **On Capella?** → service groups, 3-node Data minimum, 2-node minimum elsewhere, 27 nodes per cluster maximum
