# Encryption at rest

## Contents

- [Two different things called "encryption at rest"](#two-different-things-called-encryption-at-rest)
- [Native Encryption at Rest (8.0+, Enterprise Edition)](#native-encryption-at-rest-80-enterprise-edition)
- [Key management options](#key-management-options)
- [Key rotation](#key-rotation)
- [Pre-8.0 clusters](#pre-80-clusters)
- [Backup encryption](#backup-encryption)
- [Encryption at rest on Capella](#encryption-at-rest-on-capella)

## Two different things called "encryption at rest"

People use one phrase for two mechanisms, and conflating them produces bad compliance answers:

1. **Native Encryption at Rest** — Couchbase Server encrypts data as it writes it to disk, using keys it manages or fetches from an external KMS. **8.0+ only, Enterprise Edition only.**
2. **Volume or filesystem encryption** — the operating system, the hypervisor or the storage layer encrypts the block device underneath Couchbase. Works on any Couchbase version and any edition, because Couchbase is not involved.

If the cluster runs 7.x, or runs Community Edition, option 1 is not available to it and the honest answer is option 2. Do not describe a 7.x cluster as having Couchbase-native encryption at rest.

## Native Encryption at Rest (8.0+, Enterprise Edition)

**8.0+ only. Enterprise Edition only — not available in Community Edition.**

Couchbase Server 8.0 can natively encrypt, independently:

| Target | Notes |
|---|---|
| Bucket data | Non-ephemeral buckets; an ephemeral bucket has nothing on disk to encrypt |
| Configuration data | Cluster configuration written by the Cluster Manager |
| Audit data | The audit log |
| Logs | Server log files |

Each target can be assigned its own encryption key, so bucket data and audit data need not share custody.

The configuration surface is the Web Console (**Security → Encryption at Rest**) and two REST endpoints: `/settings/encryptionKeys` for key definitions, and `/settings/security/encryptionAtRest` for the audit, configuration and log settings. Bucket-level encryption is set on the bucket.

Two terms appear throughout the documentation and the API, and they are worth keeping straight:

- **DEK — Data Encryption Key.** The key that actually encrypts data on disk.
- **KEK — Key Encryption Key.** A key whose job is to encrypt DEKs rather than data. The KMS you choose holds or produces the KEK; the DEKs stay with Couchbase, wrapped.

Enabling encryption on an existing target means the data has to be rewritten in encrypted form. Expect elevated disk I/O on affected nodes while that proceeds, keep the cluster healthy, and do not overlap it with a rebalance. Size the window from your actual data volume and disk throughput — there is no published rule of thumb worth repeating here.

## Key management options

Three KMS choices, all 8.0+ Enterprise Edition:

**Couchbase Server as the KMS.** Couchbase generates, stores and manages the keys itself. Appropriate where the threat model does not demand separation of key custody from data custody, and where no compliance requirement names external key management. The residual risk is plain: an attacker with both the data files and the node's key store can decrypt.

**AWS KMS.** Couchbase uses AWS Key Management Service for the key-encryption key.

**KMIP-compliant KMS.** Any key manager implementing KMIP. This is the route for HSM-backed key custody and for organisations with an existing enterprise key-management estate. Couchbase authenticates to the KMIP server with a client certificate, so both sides need to trust each other's CA.

For either external option there is a prerequisite that trips up most first attempts: **every key file and certificate file must exist at exactly the path given when the key was created, on every node in the cluster.** A node that is missing the file, or has it at a different path, cannot start the encrypted services.

Choose an external KMS when a compliance standard requires key custody separated from data custody, when the organisation already runs a KMS, or when HSM protection of the key is required. Otherwise the Couchbase-managed option is materially simpler to operate.

## Key rotation

For Couchbase-managed keys, rotation is configurable rather than manual: the key definition carries a rotation interval in days and a next-rotation time, and separately a DEK rotation interval and DEK lifetime. When an encryption-at-rest key is rotated, Couchbase creates a new key and re-encrypts all DEKs with it; data encrypted under a retired DEK stays readable until it is rewritten or the DEK's lifetime expires, at which point Couchbase re-encrypts it under the active DEK.

For AWS KMS and KMIP keys, rotation happens in the external KMS; Couchbase then re-wraps its DEKs under the new key version.

Rotation frequency is a policy decision your compliance framework dictates — set the interval from that document, not from a default someone remembered. Key rotation events are audited (`encryption key rotation`, ID 8234) and the event is non-filterable, so the SIEM should see every rotation whether or not it was scheduled.

## Pre-8.0 clusters

On 7.x, meet an encryption-at-rest requirement at the storage layer: encrypted block volumes, full-disk encryption on the node, or an encrypting filesystem. Points to cover in the control narrative:

- Every path Couchbase writes to must be on encrypted storage — data, index, analytics, eventing and **log** paths, not just the data path.
- Key custody for the volume encryption lives with whoever operates the storage layer; say who that is.
- Backups written by `cbbackupmgr` land outside those volumes and need their own encryption (below).

## Backup encryption

Native Encryption at Rest protects data on cluster nodes. Backup archives are separate artifacts and are not covered by it. `cbbackupmgr` encrypts an archive with a passphrase supplied at backup time, and the same passphrase is required to restore.

Sketch, not a copy-paste command — check `cbbackupmgr` flags for your release:

```bash
cbbackupmgr backup \
  --archive /backup/couchbase-archive \
  --repo prod-cluster \
  --cluster couchbases://<host> \
  --username <user> --password <password> \
  --encrypted --passphrase "$(fetch-from-your-secrets-manager)"
```

Keep the passphrase in a secrets manager, separate from the archive, and make sure at least two people can retrieve it. An encrypted backup with a lost passphrase is unrecoverable — there is no escrow.

## Encryption at rest on Capella

Capella encrypts data at rest by default with no configuration required; the underlying keys are managed through the cloud provider's key management service. Customer-managed encryption keys (CMEK) are available on Capella, subject to plan and provider — check the Capella CMEK documentation for what your organisation's plan supports rather than assuming it is enabled.
