# Getting started with Capella

All version- and feature-sensitive statements below were verified against docs.couchbase.com in September 2026. Source URLs are given inline. No pricing appears in this file by policy — plan *names* only.

## Contents

- [Account and organization setup](#account-and-organization-setup)
- [The free tier](#the-free-tier)
- [Cluster options and Service Groups](#cluster-options-and-service-groups)
- [Creating a paid cluster](#creating-a-paid-cluster)
- [Couchbase Server version](#couchbase-server-version)
- [After cluster creation checklist](#after-cluster-creation-checklist)
- [Connecting](#connecting)
- [Management API v4](#management-api-v4)

## Account and organization setup

1. Sign up at `cloud.couchbase.com` — with an email address, a GitHub account, or a Google account. Your account is tied to an **organization**, the top-level management unit.
2. Capella creates a default project named **My First Project**. A project is a logical group of clusters (for example "production", "development").
3. Create a **cluster** inside the project.

Source: https://docs.couchbase.com/cloud/get-started/create-account.html

## The free tier

The free tier is a **forever/perpetual** offering, not a timed trial. Verified September 2026 against https://docs.couchbase.com/cloud/get-started/create-account.html

- One free tier **operational** cluster per organization, at any time.
- A single node running the Data, Query, Index, and Search Services.
- Available on AWS, Google Cloud, and Azure, in a **restricted region list**. Per the Management API reference for `Create Free Tier Cluster`: AWS `us-east-2`, `eu-west-1`, `ap-southeast-1`; GCP `us-central1`, `europe-west1`, `asia-east1`; Azure `eastus`, `swedencentral`, `koreacentral`. Only name, description, cloud provider, region, and CIDR are configurable. (Source: https://docs.couchbase.com/cloud/management-api-reference/index.html)
- **Free tier App Services** are also available and link automatically to the free tier operational cluster.
- **Not available for Capella Analytics** — the free tier is Capella Operational only.
- Not available on free tier clusters: backup/restore, private endpoint service, network peering, audit logs, alert integrations, CMEK, on/off schedules, and the Health Advisor dashboard.
- **Inactivity behaviour:** after 72 hours of inactivity Capella turns the cluster (and any linked App Services) off, preserving data and state. After 30 days of inactivity Capella *deletes* the cluster and any linked App Services. Warning emails go out after the 72-hour turn-off.
- Accounts on a paid plan may run a free tier cluster alongside paid clusters. **Upgrading from the free tier plan to a paid Support plan deletes the existing free tier cluster** — move data out first with `cbbackupmgr`.

Historical note (do not remove): earlier Capella offered a **30-day free trial**. Accounts from that era are converted to the free tier plan when the trial ends; expired trial accounts can click **Activate Free Tier**.

Free tier is for development and evaluation. Treat it as having no production SLA.

## Cluster options and Service Groups

When creating a paid cluster you first pick a **Cluster Option**. Source: https://docs.couchbase.com/cloud/clusters/databases.html

| Cluster Option | What you get |
|---|---|
| **Free** | The free tier cluster described above. |
| **Single Node** | One node, one Service Group, one Availability Zone. Prototyping and learning. Defaults to Data + Index + Query; Search, Analytics, or Eventing can be added on the larger compute configuration. |
| **Multi-Node** | Pre-configured 3-, 5-, or 7-node templates with one or more Service Groups. Supports multiple Availability Zones. |
| **Custom** | You create Service Groups and assign nodes, compute, storage, and IOPS per group. Defaults to 4 Service Groups / 9 nodes; maximum 27 nodes across all Service Groups. Supports multiple Availability Zones. |

A **Service Group** is a set of nodes that share one compute and storage configuration and run the same set of Services. This is how Multi-Dimensional Scaling is expressed in Capella — size each Service independently by putting it in its own Service Group.

Services available: Data, Query, Index, **the Search Service**, Eventing, and the Analytics Service. Search, Eventing, and Analytics each want a minimum of 2 nodes for production, and cannot run on a Single Node cluster using the smallest (2 vCPU / 8 GB) compute configuration.

RAM note from the docs: Capella reserves roughly 20% of a node's RAM for the operating system and divides the remainder evenly between the Services deployed in that Service Group. Running several Services in one group therefore starves each of them — give production Services dedicated Service Groups.

**Support Plans** are named **Basic**, **Developer Pro**, and **Enterprise**. Availability varies by cluster option; Basic supports only a single Availability Zone. Some features (private endpoints, for one) require Developer Pro or Enterprise. Costs are out of scope for this repo.

## Creating a paid cluster

Capella UI: **Operational → + Create Cluster**. Source: https://docs.couchbase.com/cloud/clusters/create-database.html

Decisions, in the order the UI asks for them:

1. **Project** — which project owns the cluster. Requires the Project Owner or Cluster Manager role.
2. **Cluster Name** and description.
3. **Cloud Service Provider and Region** — AWS, Google Cloud, or Azure. Match the region your application runs in. (https://docs.couchbase.com/cloud/clouds/cloud-providers.html)
4. **CIDR Block** — accept the default or set your own IPv4 block. If you plan to use VPC peering or private endpoints, **set this deliberately so it does not overlap your own VPC/VNet CIDR.** This cannot be fixed later without redeploying.
5. **Couchbase Server version** — see below.
6. **Cluster Option** — Free, Single Node, Multi-Node, or Custom, then Services / Service Groups / compute / storage / IOPS.
7. **Support Plan**.
8. **Availability Zone** configuration — Single or Multiple. Multi-AZ is the production choice; Basic plan clusters are single-AZ only. Multi-region high availability is built with separate clusters joined by XDCR, not by a single stretched cluster.

Some organizations also see a **Restrict public access** option at CIDR-block time, which limits the cluster to Capella's private networking options.

**Deployment time:** the docs say deployment typically takes **less than 5 minutes**, varying with cluster size and cloud provider performance. Watch for the cluster status to reach **Healthy**.

## Couchbase Server version

The latest supported Couchbase Server version for Capella operational clusters is **8.0** (verified September 2026, https://docs.couchbase.com/cloud/clusters/databases.html). You may choose an earlier minor version for application compatibility. Capella always deploys the latest available *patch* within the minor version you choose, and offers version upgrades as they become available.

Clusters on Couchbase Server **7.6 or later** have guardrails that automatically block specific cluster operations when system thresholds are crossed, to avoid outages.

## After cluster creation checklist

1. **Add an allowed IP** — Settings → Allowed IP (see `references/networking.md`).
2. **Create cluster access credentials** — Settings → Cluster Access → Create Access (see `references/credentials.md`).
3. **Create a bucket**, then scopes and collections — Couchbase's data hierarchy is Bucket → Scope → Collection.
4. **Get the connection string** — from the cluster's **Connect → SDK** tab.
5. **Download the security certificate** if your SDK needs it. The Capella root certificate is bundled with all Couchbase SDKs except the C SDK (libcouchbase).
6. **Test connectivity** from your application environment.

## Connecting

Take the **public connection string** from **Connect → SDK** in the Capella UI rather than constructing it by hand — the Connect tab also generates a pre-populated snippet or full code sample per SDK language. The scheme is `couchbases://` (TLS required). Never use plaintext `couchbase://` with Capella.

Capella publishes IPv4 records; connecting from an IPv6-only environment is not supported.

Source: https://docs.couchbase.com/cloud/get-started/connect.html

```python
from couchbase.cluster import Cluster
from couchbase.auth import PasswordAuthenticator
from couchbase.options import ClusterOptions, ClusterTimeoutOptions
from datetime import timedelta
import os

cluster = Cluster(
    os.environ["CB_CONNSTR"],          # couchbases://... copied from Connect -> SDK
    ClusterOptions(
        PasswordAuthenticator(os.environ["CB_USERNAME"], os.environ["CB_PASSWORD"]),
        timeout_options=ClusterTimeoutOptions(kv_timeout=timedelta(seconds=10)),
    ),
)
cluster.wait_until_ready(timedelta(seconds=30))
```

Use the **cluster access credentials** here — not your Capella login.

## Management API v4

Base URL `https://cloudapi.cloud.couchbase.com`, with all resources under `/v4`, for example:

```
GET https://cloudapi.cloud.couchbase.com/v4/organizations
GET https://cloudapi.cloud.couchbase.com/v4/organizations/{organizationId}/projects
```

Authenticate with an organization API key passed as a Bearer token. `PUT` requests support optimistic concurrency with `If-Match` and ETags. The API is semantically versioned and is documented as backward compatible apart from critical security fixes and unavoidable architectural changes. Verified current at v4 in September 2026.

Sources: https://docs.couchbase.com/cloud/management-api-guide/management-api-intro.html, https://docs.couchbase.com/app-services/management-api-guide/management-api-use.html
