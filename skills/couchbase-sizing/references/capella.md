# Capella cluster sizing

Sizing a Capella cluster means choosing **service groups**, the compute instance type and disk configuration for each, and the node count per group. This reference covers the selection logic.

> **This reference contains no pricing.** Capella tier names, instance types and technical characteristics are in scope; costs, rates, credit figures and cost-comparison claims are not. They change, they vary by contract, and they are a commercial conversation rather than a sizing input. If the user asks what something costs, point them at Couchbase or their account team — do not estimate.
>
> Specific instance types and service-group options change over time. Verify current details in the [Capella documentation](https://docs.couchbase.com/cloud/clusters/sizing.html).

## Contents

- [How Capella sizing differs from self-managed](#how-capella-sizing-differs-from-self-managed)
- [Documented limits and minimums](#documented-limits-and-minimums)
- [The selection logic](#the-selection-logic)
- [Workload-to-tier matching](#workload-to-tier-matching)
- [Scaling compute and storage](#scaling-compute-and-storage)
- [Multi-cluster patterns](#multi-cluster-patterns)
- [Right-sizing](#right-sizing)
- [Quick decision tree](#quick-decision-tree)

## How Capella sizing differs from self-managed

- **Service groups** are the unit of configuration: a set of nodes running a specified set of services, with their own compute instance type and disk configuration
- **Compute instance type** determines the vCPUs and memory provisioned per node in that service group
- **Storage type and IOPS** are configurable within what the cloud provider offers (see below)
- **Replicas and high availability** are managed by Capella; you choose the replica count, Capella places the copies
- **Backup, monitoring and alerting** are provided by the platform
- **Upgrades** are managed — no rolling-upgrade runbook to write
- **Capella distributes each node's memory** between the operating system and all services deployed in that service group

You DO still need to size:
- Service groups and which services go in each
- Compute instance type per service group
- Node count per service group
- Replica count
- Disk type and IOPS
- Number of clusters, if you need multi-region or workload isolation

## Documented limits and minimums

| Constraint | Value |
|---|---|
| Minimum nodes in a Data service group | 3 |
| Minimum nodes in any other service group | 2 |
| Maximum nodes per cluster | 27 |
| Data Service | Mandatory; cannot be removed |
| Single Node clusters | Cannot have additional service groups; scaling one out requires a minimum of 4 vCPUs / 16 GB RAM |

**Storage options by cloud provider:**

| Provider | Disk types | IOPS |
|---|---|---|
| AWS | gp3, io2 | Configurable above the default (not below) |
| GCP | PD-SSD only | Automatic: documented as 30 read and 30 write IOPS per GB |
| Azure | Premium SSD, Ultra disk | Provider-determined ranges; increasing storage requires selecting a new disk type |

Capella Server 7.6 and later also applies **guardrails** that limit certain operations beyond configured thresholds.

## The selection logic

### Step 1: estimate workload size

Use the calculations from `memory.md` and `disk.md` to get:
- Total RAM needed across the cluster (sum of all services)
- Total storage needed
- Peak QPS for sizing CPU

### Step 2: pick the smallest compute instance type that fits

Match the instance type so the node's memory comfortably exceeds what the services on it need. Couchbase's documented guidance for self-managed applies here too: allocate **no more than 90% of a node's memory** across services (80% on small-memory nodes), leaving the rest for the OS. In Capella the platform does that split for you within the service group.

A practical target *(estimate)* is to sit meaningfully below the node's capacity at steady state, so spikes, compaction and rebalance have room. Running a node at its ceiling in steady state leaves nothing for the abnormal day.

Don't over-pick either — Capella supports online scaling, so start from the measured requirement rather than an aspirational one.

### Step 3: pick node count

Apply the node-count rules from `nodes.md`:
- At least 3 for replica=1 production
- At least 4 if you want N-1 fault tolerance with replica=2
- Higher counts for higher fault tolerance or throughput

### Step 4: validate with the N-1 rule

After picking the tier and node count, recompute: can the cluster handle the workload with one node missing?

If not, either:
- Pick a larger tier
- Add more nodes of the same tier

### Step 5: define service groups

Separate the workload into service groups so one service's appetite doesn't force every node in the cluster to be large:

- **Data service group** — sized for the working set and metadata by the documented formula in `memory.md`. Minimum 3 nodes
- **Query / Index service group** — sized by the Index service's needs, which depend on the index storage mode. Minimum 2 nodes
- **Search service group** — the largest memory requirement when vector indexes are involved. Minimum 2 nodes
- **Eventing** — sized by the measured footprint of the deployed functions. Minimum 2 nodes
- **Analytics** — its own group; minimum service quota 1024 MB and a storage-heavy profile

Remember the cluster-wide maximum of 27 nodes when planning the split across groups.

## Workload-to-tier matching

Rough guidance *(estimate — these are conversation starters, not specifications; the document counts in particular depend entirely on document size and working-set fraction)*:

| Workload | Cluster shape |
|---|---|
| Dev / staging | Single Node or a small 3-node cluster, all services in one group |
| Small production | 3 nodes, all services in one group |
| Medium production | Split into Data and Query/Index service groups |
| Large production | Dedicated service group per service |
| Vector / Search heavy | A Search service group on the largest-memory instance type available; vector index size drives it |
| Analytics workload | Dedicated Analytics service group — or a separate Capella Analytics / Couchbase Enterprise Analytics deployment |
| Multi-region / workload isolation | Multiple clusters, each sized to its own role, linked by XDCR |

## Scaling compute and storage

Compute and storage are configured separately within a service group, so they can be adjusted independently:

- **Compute** — change the instance type for the service group to alter vCPUs and memory per node
- **Storage** — expand capacity, and on AWS raise provisioned IOPS above the default. On GCP, IOPS follows capacity automatically (30 read / 30 write IOPS per GB). On Azure, increasing storage may require selecting a different disk type

This matters most where one dimension dominates: a large, cold dataset needs disk without proportionate compute; a heavy query workload over a modest dataset needs the reverse.

## Multi-cluster patterns

For multi-region or workload-isolation, deploy multiple Capella clusters:

**Pattern: regional with XDCR**
- One cluster per region
- XDCR replicates writes — typically active-passive, with a primary region accepting writes and others serving reads
- Requires WAN bandwidth for XDCR; see `network.md`
- If you use active-active, decide the XDCR conflict-resolution policy (sequence-number is the default; timestamp/LWW must be selected at bucket creation and needs NTP)

**Pattern: workload isolation**
- One cluster for OLTP (Data + Query)
- A separate analytics deployment — Capella Analytics or Couchbase Enterprise Analytics
- A separate cluster for development / staging
- Each is sized exactly for its own workload rather than for the union

**Pattern: customer isolation (B2B SaaS)**
- One cluster per customer or per customer tier
- Highest isolation, highest operational surface
- Justified when one customer's workload can impact others, or when compliance requires hard isolation
- Compare against the scope-per-tenant pattern inside one cluster, which is far cheaper operationally — see `workload-shapes.md`

## Right-sizing

Capella supports online scaling, so the correct starting point is the **measured or calculated** requirement, not an aspirational one. Practices that keep a cluster correctly sized:

**Start from the documented formula.** Size the Data service with the published RAM formula in `memory.md`, then scale from measurement rather than from a guessed working-set fraction.

**Replace the working-set assumption with a measurement.** If you sized at 50% working set and the running cluster shows a resident ratio implying 20%, resize. The resident item ratio and cache-miss rate are the signals.

**Drop unused indexes.** Each index consumes memory in the Index or Search service, which drives instance-type selection. Use the Index Advisor and the index last-used statistics to find candidates.

**Pause non-production clusters.** Dev and staging clusters can be paused when not in use.

**Archive cold data.** Move data past its useful retention out of the active cluster — delete it, or back it up and delete it if it must remain recoverable. This reduces the dataset that drives every other number in the sizing.

**Scale online rather than pre-provisioning.** Adding capacity later is a supported operation; over-provisioning from day one is not recoverable except by resizing anyway.

## Quick decision tree

- **Sizing for the first time?** Use the documented formula in `memory.md`, then pick the smallest instance type that carries it with headroom
- **Production?** Minimum 3 nodes in the Data service group, replica=1; validate the N-1 case
- **Durable writes must survive a node failure?** replica=2 — with replica=1, `majority` writes become impossible during a failure
- **Vector workload?** The largest-memory instance type for the Search service group; vector indexes dominate the sizing
- **Multi-region?** Multiple clusters with XDCR; size the WAN link (`network.md`) and choose the conflict-resolution policy before the first write
- **Planning node counts?** Remember the 27-node-per-cluster maximum and the 3/2 service-group minimums
- **Asked about price?** Out of scope here — refer to Couchbase or the account team. Tier names and technical specs are fine to discuss; costs are not
- **Workload changing?** Capella supports online scaling — size from measurement, not from worst-case imagination
