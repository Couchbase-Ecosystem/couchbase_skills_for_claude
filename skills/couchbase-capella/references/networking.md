# Capella networking

Verified against docs.couchbase.com in September 2026. Source URLs inline.

## Contents

- [Allowed IPs (public internet access)](#allowed-ips-public-internet-access)
- [VPC and VNet peering](#vpc-and-vnet-peering)
- [Private endpoints](#private-endpoints)
- [Ports](#ports)
- [App Services networking](#app-services-networking)
- [Recommended networking by environment](#recommended-networking-by-environment)
- [Troubleshooting connectivity](#troubleshooting-connectivity)

## Allowed IPs (public internet access)

The simplest connectivity option: add your application's public IP(s) to the cluster's allowlist. Capella denies every connection to and from an IP not on the list.

**Capella UI → your cluster → Settings → Allowed IP → Create Allowed IP**

Accepts a single IPv4 address (`141.193.213.10`) or a CIDR block (`141.193.213.0/24`). **Add Current IP Address** fills in your own external IP.

Each entry is **Permanent** or **Temporary**. Temporary entries carry an expiration date and time; once expired the entry shows status **Expired** and must be deleted and recreated to be re-enabled. Other statuses are Active, Pending, and Failed (a failed entry also has to be deleted and recreated).

Gotchas:
- Cloud provider NAT gateways change IPs on restart. Pin a static Elastic IP (AWS) or equivalent.
- CI/CD pipelines often have dynamic IPs — allow the CI provider's published range, or run jobs behind a fixed egress proxy.
- `0.0.0.0/0` allows all internet traffic. The UI offers it; never use it in production.

Source: https://docs.couchbase.com/cloud/clusters/allow-ip-address.html

## VPC and VNet peering

Peering co-locates your application network with the Capella network so traffic stays off the public internet, cutting latency and egress cost.

Supported on **AWS, GCP, and Azure**. Capella does **not** support peering between different cloud providers — a GCP-hosted Capella cluster cannot peer with an AWS-hosted application.

Sources: https://docs.couchbase.com/cloud/clouds/private-network.html, https://docs.couchbase.com/cloud/clouds/vpc-peering/peer-aws.html

**AWS setup outline:**

1. Confirm the CIDR block you chose at cluster-creation time does not overlap your application VPC's CIDR. (You can read the cluster CIDR from the UI or the Management API.) There is no fixed default Capella CIDR to assume — check the cluster.
2. Capella UI → your cluster → networking/peering → add a peering connection, supplying the AWS region and your VPC's CIDR block.
3. Accept the peering request in the AWS console: `aws ec2 accept-vpc-peering-connection --vpc-peering-connection-id=pcx-...`
4. Associate your VPC with the Capella private hosted zone so Capella hostnames resolve, for example with `aws route53 associate-vpc-with-hosted-zone`.
5. Add a route in your VPC route tables sending the Capella CIDR through the peering connection.
6. If your VPC has outbound security groups restricting egress, add the Capella CIDR there too.

Azure uses VNet peering and GCP uses VPC Network Peering, following the same shape; see the per-cloud pages linked from the peering overview.

## Private endpoints

Private endpoints give your network a private path to the cluster without peering route-table changes. Capella supports all three clouds, under the cloud-native names:

| Cloud | Capella feature name | Doc |
|---|---|---|
| AWS | **AWS PrivateLink** | https://docs.couchbase.com/cloud/security/add-aws-private-link.html |
| Azure | **Azure Private Link** | https://docs.couchbase.com/cloud/security/add-azure-private-link.html |
| GCP | **GCP Private Service Connect** | https://docs.couchbase.com/cloud/security/add-gcp-private-link.html |

**Prerequisites (AWS and GCP pages both state this explicitly):** the cluster must be on the **Developer Pro** or **Enterprise** Support Plan, and you need the Project Owner role. Private endpoints on AWS and GCP additionally support XDCR and Prometheus scraping, subject to the conditions on each page.

**AWS PrivateLink flow:**

1. Capella UI → enable the Private Endpoint Service for the cluster.
2. Add a private endpoint; Capella returns the command/service details.
3. Create the VPC endpoint in your AWS account against the Capella endpoint service.
4. In the AWS VPC console, **Modify private DNS name → Enable for this endpoint**, and make sure the VPC has **Enable DNS resolution** and **Enable DNS hostnames** turned on.
5. Add an inbound security-group rule from your VPC IPv4 CIDR for ports `18091-18203` and `11207-11308` (plus `20091-20117` if you use private endpoints over XDCR).
6. Configure inbound and outbound network ACL rules for your VPC CIDR.
7. Verify the connection.

**Connection string with a private endpoint:** because step 4 enables *private DNS names*, the cluster's normal published hostname resolves to the private endpoint from inside your VPC. Use the same connection string from the Connect tab. Do not invent a separate `private.` hostname — the documented AWS procedure is DNS-based, and the docs do not publish a distinct private connection-string template.

## Ports

From the AWS PrivateLink security-group step (https://docs.couchbase.com/cloud/security/add-aws-private-link.html):

| Range | Purpose |
|---|---|
| `11207-11308` | KV / data traffic (TLS) |
| `18091-18203` | Management and service REST endpoints (TLS) |
| `20091-20117` | Additional range required for private endpoints over XDCR |

## App Services networking

App Services have their own allowed-IP list and their own private endpoint support, separate from the operational cluster's:

- Each App Service has an allowed IP list of up to **26 entries**, single IPs or CIDR blocks, permanent or temporary. This list gates the Admin and Metrics REST APIs. (https://docs.couchbase.com/app-services/app-services/accessing-admin-apis.html)
- **Private Endpoints for App Services** are available on **AWS only** — configurable via the Management API since July 2025 and via the Capella UI since March 2026. (https://docs.couchbase.com/app-services/release-notes/release-notes.html)
- Since June 2026, access to the App Services Metrics and Admin REST APIs over a private endpoint no longer requires the associated Metrics or Admin user to be on the IP allow list.
- On **Azure**, since July 2026 you can pin a **static CIDR range** for the subnet hosting the App Service load balancer (`loadBalancerCidr` at create time). It persists across turning the App Service off and on, which prevents CIDR conflicts when peering. It is **immutable after creation** — the Management API rejects a different value on update.

## Recommended networking by environment

| Environment | Recommended connectivity |
|---|---|
| Development / local | Allowed IP (your public IP), preferably a temporary entry |
| Staging (cloud-hosted) | VPC/VNet peering in the same region as the cluster |
| Production (AWS) | AWS PrivateLink, or peering (Developer Pro / Enterprise for PrivateLink) |
| Production (Azure) | Azure Private Link, or VNet peering |
| Production (GCP) | GCP Private Service Connect, or VPC peering |
| CI/CD pipelines | Allowed IP for the CI provider's ranges, or a fixed egress proxy |

## Troubleshooting connectivity

**Connection refused / timeout**

1. Check the allowed IP list — is your current egress IP on it, and is the entry Active rather than Expired or Pending?
2. Resolve the cluster hostname. With a private endpoint and private DNS enabled it should resolve to a private address from inside your VPC; from outside it resolves publicly.
3. Check that the KV and management port ranges above are open in your security groups and network ACLs.
4. Confirm the connection string uses `couchbases://` (TLS), not `couchbase://`.
5. Confirm you are not on an IPv6-only network — Capella publishes IPv4 records.

**Authentication failed**

Verify you are using **cluster access credentials** (Settings → Cluster Access), not your Capella login or an organization API key.
