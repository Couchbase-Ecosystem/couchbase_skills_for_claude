# XDCR troubleshooting

## Contents

- [Diagnostic workflow](#diagnostic-workflow)
- [changes_left is non-zero and growing](#changes_left-is-non-zero-and-growing)
- [changes_left is stable but non-zero](#changes_left-is-stable-but-non-zero)
- [docs_failed_cr_source is non-zero](#docs_failed_cr_source-is-non-zero)
- [Replication status is error](#replication-status-is-error)
- [Documents silently not replicating](#documents-silently-not-replicating)
- [Replication lag spikes during rebalance](#replication-lag-spikes-during-rebalance)
- [Document count mismatch between source and target](#document-count-mismatch-between-source-and-target)
- [Proving fidelity with xdcrDiffer](#proving-fidelity-with-xdcrdiffer)

## Diagnostic workflow

1. **XDCR statistics** — check `changes_left`, `docs_failed_cr_source`, and `rate_replication` in the Web Console or via the stats REST API.
2. **Replication status** — confirm the replication is running, not paused or errored. On 8.0+, also check **incoming replications** on the target cluster, which shows the stream from the receiving end.
3. **Eventing** — if lag coincides with a mutation-rate spike, check whether an Eventing function is also writing into the source keyspace and doubling the mutation load. In bidirectional topologies, also check for Eventing-induced replication loops.
4. **Target cluster health** — a healthy source with a struggling target looks identical to a slow source from the source side.

## changes_left is non-zero and growing

XDCR cannot keep up with the source mutation rate. In rough order of cost to try:

- Narrow the filter or the collection mapping so less data crosses.
- Increase `Source Nozzles per Node` and `Target Nozzles per Node` together, keeping source ≤ target, in small steps. Watch source CPU and the Web Console's maximum-processes warning.
- Raise `Batch Count` and `Batch Size` — the documentation notes that increasing these by two or three times typically improves transmission rates, provided the target can persist the result.
- Check whether `networkUsageLimit` is capping you; remember the per-node limit is the cluster limit divided by node count.
- Check compression: `Auto` only compresses when the target runs Couchbase Server 5.5 or later.
- Add Data nodes on source or target to spread per-node load.
- Lower `priority` during a spike to protect foreground workload. This protects the application; it does not fix the throughput shortfall.

If `enableCrossClusterVersioning` was recently enabled, note that optimistic replication no longer applies, which changes the profile for small documents.

## changes_left is stable but non-zero

Normal during initial backfill after creating a replication, or after a restream. A large value at creation is expected. Watch the trend: consistently decreasing means it is progressing. Only act if it is flat or growing.

## docs_failed_cr_source is non-zero

The source lost conflict resolution — the target's version won. Expected and normal in active-active. It is a problem only when it is growing fast relative to total writes, which means frequent conflicts and correspondingly frequent discarded writes.

In **active-passive**, any `docs_failed_cr_source` is a red flag: something is writing to the target that should not be.

On 8.0+ with Conflict Logging enabled, inspect the conflict log collection to see *which* documents are losing, not just how many. Remember that logging is best-effort and stops under conflict surges, so the collection undercounts.

## Replication status is error

Check the Web Console's XDCR view for the error text, and the XDCR logs (raise the level with `Logging Level`, or `genericServicesLogLevel` on 8.0+).

| Symptom | Likely cause | Fix |
|---|---|---|
| Authentication failure | Credentials in the remote cluster reference are wrong or expired | Update the reference |
| Bucket not found | Target bucket renamed or deleted | Verify the name; recreate the bucket |
| TLS handshake failure / certificate expired | Target cluster certificate rotated or expired | Rotate on the target, update the reference |
| Connection refused / timeouts | Network path broken | Check firewalls, peering, security groups, and that the required Couchbase ports are open between clusters |
| Too many connections | Nozzle count times node count exceeds the target's connection capacity | Reduce target nozzles; check the maximum-processes warning in the UI |
| Replication refuses to be created between two buckets | The buckets have different conflict resolution policies | The policy cannot be changed after bucket creation — recreate one bucket with the matching policy and move the data |

## Documents silently not replicating

Four distinct causes, all of which produce a *healthy-looking* replication:

1. **Explicit collection mapping with a missing rule.** With `collectionsExplicitMapping=true`, implicit bucket-level mapping is off, so a source collection absent from `colMappingRules` is simply not replicated, with no error. Audit the rules against the current collection list on both clusters whenever collections are added.
2. **More than 10 user xattrs on the document, under XDCR Active-Active with Sync Gateway.** XDCR silently skips the document and the clusters diverge on it. The **only** signal is the Prometheus stat **`subdoc_cmd_docs_skipped`** incrementing. Alert on it. Full detail in `topology.md`.
3. **The filter expression excludes it.** Remember matching is case-sensitive, uses `REGEXP_CONTAINS` rather than `LIKE`, and that `EXISTS` is the only collection operator available.
4. **Binary documents excluded** by the dedicated flag, regardless of the filter expression.

## Replication lag spikes during rebalance

XDCR pauses and restarts replication streams during a source or target rebalance; `changes_left` spikes and then recovers. This is expected. If it has not recovered some time after the rebalance completes, investigate connectivity and target health rather than assuming it will settle.

The checkpoint interval (default 600 s) governs how much work is redone on restart — shortening it reduces rework at the cost of more checkpoint computation and persistence.

## Document count mismatch between source and target

Differing counts are common and usually benign. Known causes:

- **TTL** — documents expired on one side but not yet the other.
- **Filtering** — some documents are intentionally not replicated.
- **Deletion filters** — deletes may deliberately not propagate in some contexts.
- **Transactions** — transaction metadata documents are never replicated, so a cluster used for transactions will always differ from its target.
- **Silently skipped documents** — see above.

Do not use document count parity as a fidelity test.

## Proving fidelity with xdcrDiffer

`xdcrDiffer` compares document data between source and target clusters participating in XDCR and reports differences in content, metadata, or presence. From **8.0** it is included in the Server installation package; on earlier versions it had to be built from the xdcrDiffer GitHub repository. This is the supported way to verify a replication is actually faithful. ([What's New in 8.0](https://docs.couchbase.com/server/current/introduction/whats-new.html))

For spot checks on individual keys, fetch the same key from both clusters and compare values and CAS.
