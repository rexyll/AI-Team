# Protected reconciliation approval grant custody

## Scope

This document defines the Host-side custody boundary for one-use ReconciliationApprovalGrant capabilities. It addresses secure storage and restoration across Host process restarts; it does not implement an identity provider, grant encryption primitive, audit-head anchor, reconciliation executor, or deployment mutation.

The implementation is split between:

- runtime/deployment_reconciliation_grant_vault.py: ciphertext-envelope persistence and the injected ReconciliationGrantProtector contract.
- runtime/deployment_reconciliation_authority.py: approval issuance ordering, audit-bound grant restoration, and one-use consumption.
- runtime/deployment_reconciliation_audit_store.py: append-only source of truth for approval issuance and consumption state.

## Security boundary

The vault accepts a ReconciliationGrantProtector with two methods:

- seal(plaintext, encryption_context) -> ciphertext
- unseal(ciphertext, encryption_context) -> plaintext

A production implementation must use a key managed outside the writable grant directory, provide authenticated encryption, and bind every context field as authenticated additional data. For cloud KMS services with small direct-encryption limits, the adapter should use envelope encryption: a data-encryption key encrypts the grant and the KMS wraps that data key. The repository does not supply a software-key fallback and does not persist key material.

The canonical encryption context binds purpose and schema version; approval ID and operation ID; provider, project and environment; approval expiry; proposal digest; and evidence digest.

The local JSON envelope exposes only this non-secret scope metadata and a base64-encoded ciphertext. The requester/approver snapshots, proposal, evidence, snapshot receipt and bearer token are inside the authenticated ciphertext. The bearer token is separately represented in the audit chain only by its SHA-256 digest.

## Filesystem handling

On POSIX, the vault requires a service-account-owned directory with no group/other access and writes grant files with mode 0600. It uses exclusive-create semantics, refuses to overwrite an approval ID, avoids following symlinks, checks regular-file ownership/link count/mode on read, and fsyncs the file and containing directory after writes/deletes.

The module does not currently validate Windows NTFS ACLs. On Windows, the Host deployment service must provision a dedicated service account and restrictive directory/file ACLs. A production deployment must not treat the POSIX checks as evidence of Windows ACL enforcement.

## Issuance and recovery ordering

When a vault is injected into ReconciliationApprovalAuthority, issuance order is:

1. Read and validate a fresh Host snapshot.
2. Authenticate distinct requester and approver identities.
3. Build the exact, short-lived, one-use grant.
4. Persist the encrypted envelope through grant_vault.save().
5. Append the reconciliation_approved event with the token digest.
6. Return the in-memory grant plus its non-secret storage reference.

If KMS protection or durable vault storage fails, the authority records a rejection and does not append an approval event or return a consumable grant. If the audit append reports an error, its outcome may be ambiguous: the event might have committed even though the caller did not receive confirmation. In that case, the encrypted envelope is retained rather than deleted.

After a Host restart, the caller can invoke restore_grant(approval_id). The authority asks the vault to rebuild a reference and decrypt the envelope, then verifies all of the following against the append-only audit history:

- the approval ID is globally unique across the complete verified audit chain, with exactly one reconciliation_proposed and one reconciliation_approved event;
- the proposal precedes the approval;
- operation/project/environment, journal phase, deployment IDs and immutable runtime IDs match the grant exactly;
- requester and approver identities match the two audit actors;
- proposal digest, evidence digest, expiry and bearer-token digest match;
- no consumption-start, consumed or rejected event has already burned the approval.

The audit ledger is authoritative. A ciphertext without a matching durable approval event is never returned by restore_grant(). A claimed, consumed, or rejected approval cannot be restored for reuse. consume() still performs the atomic one-use claim against the audit store and rereads the current Host snapshot; restoring a grant does not consume it or execute reconciliation.

If a process crashes after the encrypted envelope is saved but before an approval event commits, the envelope is an orphan and is not consumable. It expires according to the embedded approval TTL. A future production adapter may add bounded orphan cleanup after it can prove no approval event exists and coordinate with issuance; cleanup must never infer authority from a missing in-memory reference.

## Failure and trust model

- KMS/SecretStore unavailable: fail closed; do not issue a usable grant.
- Ciphertext, reference, AAD context or decrypted payload mismatch: fail closed.
- Missing, duplicate, reordered or mismatched audit events: fail closed.
- Ambiguous audit append: retain ciphertext for deterministic ledger-based recovery; do not delete a potentially approved grant.
- Consumption started but not completed: terminal one-use claim; require fresh dual approval.
- Audit ledger tampering: the local hash chain detects edits/reordering; the provider-neutral external CAS checkpoint contract is documented in deployment-reconciliation-external-audit-anchor.md. A real external anchor adapter and remote retention are still required in production.
- Multi-host authority: the current same-host file-lock store is not a distributed transaction. A multi-host deployment needs a shared database uniqueness/transaction boundary or centralized approval service.

## Verification status and production gate

The fake protector in unit tests is intentionally non-cryptographic. It tests serialization, context binding, refusal paths and restart semantics; it is not evidence of encryption strength or a production KMS integration.

The repository currently has no configured production ReconciliationGrantProtector adapter, no production IdP-backed HostAuthenticator, no externally anchored audit head, and no operator-provisioned production daemon/socket trust configuration. The vault boundary and authority ordering are testable code contracts only until the deployment selects and configures those trust roots.

This subsystem does not add a mutation executor. It cannot update deployment pointers, Router selectors, journal phases, reservations, or runtime lifecycle.
