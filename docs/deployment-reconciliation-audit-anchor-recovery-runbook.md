# Reconciliation external audit-anchor incident runbook

## Purpose and stop condition

Use this runbook when ExternallyAnchoredReconciliationAuditStore refuses reads/writes because the local JSONL audit head and external trusted checkpoint do not match, the anchor is unavailable, or a compare-and-set result is ambiguous.

**Default posture: fail closed.** Freeze new reconciliation proposal/approval/consumption requests and leave all deployment state untouched. Do not execute reconciliation, rollback, selector/active-pointer changes, journal phase transitions, reservation release or runtime lifecycle actions as part of audit recovery.

There is intentionally no automatic command that advances an external checkpoint to match a local ledger. Such a command could bless attacker-injected or otherwise unapproved local events.

## Immediate containment

1. Put the reconciliation approval endpoint/worker into maintenance mode or stop the service instance that owns the affected audit store. Keep ordinary read-only deployment diagnostics separate and unchanged.
2. Do not call private append/truncate/rewrite APIs, edit the JSONL file, delete grant envelopes, reset the external checkpoint, or retry an ambiguous operation blindly.
3. Preserve the local audit directory and external anchor service evidence before restarting or changing permissions.

## Evidence to preserve

Capture the following in a restricted incident bundle:

- A byte-for-byte copy of the complete local deployment-reconciliation-audit.jsonl file, its SHA-256, file size, timestamps, owner/mode, and the exact Host software commit.
- A copy of the audit directory metadata and lock-file metadata. Do not modify the source files to make the copy.
- The external anchor's read-only checkpoint response: immutable ledger_id/namespace, configured expected_ledger_id, sequence, digest, service/version identifier, request/correlation ID, and trusted timestamp. Confirm the adapter identity and remote storage key refer to the same environment/project ledger. Preserve the anchor service's own audit/retention record for the read.
- Host service logs surrounding the last successful and failed audit operation, including approval ID/operation ID where available and whether local append/fsync and external CAS were attempted.
- A byte-for-byte restricted backup of encrypted grant-vault envelopes and metadata. Do not decrypt/export bearer tokens for routine diagnosis.
- Relevant IdP/KMS/SecretStore access/audit logs from the same time window, when those systems are configured.

Record all timestamps with timezone/UTC and keep the original bundle immutable.

## Classify the mismatch

Let L be the locally verified audit head and R the independently read external checkpoint.

### L == R

The checkpoint and ledger currently agree. This does not prove that no earlier request failed; inspect service logs and pending grant records before reopening the approval path.

### L is ahead of R

The local chain contains an unanchored suffix. Possible causes include a crash after local fsync but before external CAS, a lost/ambiguous anchor response, a writer that bypassed the anchored wrapper, or local tampering.

Do not assume this is a harmless crash. Compare every suffix event with Host operation logs, requester/approver IdP audit, grant-vault envelope metadata, KMS/SecretStore access logs, and the anchor provider's CAS request history. Any approval event without a verifiable end-to-end issuance record must be considered untrusted.

### L is behind R

The local ledger may have been truncated, rolled back, restored from an older backup, or the Host may be pointed at the wrong audit directory. Do not reset the external head to the local value. Locate the exact ledger backup whose hash-chain head matches R; preserve all candidate copies.

### L and R have the same sequence but different digests

Treat this as a fork or tampering incident. Do not attempt automatic reconciliation. Preserve all local and remote evidence and involve the security owner.

### External anchor unavailable

Keep the service fail-closed. Do not substitute a cached checkpoint, local file, environment variable, or test fake as a trusted head. Restore the anchor provider's availability and query its authoritative checkpoint before resuming.

## Recovery decision gate

Recovery requires an independently authenticated change/incident record and two-person review outside the affected reconciliation authority. The review must determine:

- Which exact ledger bytes and external checkpoint are authoritative.
- Whether the discrepancy is explained by a known crash window or indicates a bypass/tampering event.
- Whether any unreturned, unconsumed, or ambiguous approval grants exist in the local suffix.
- Whether any requester/approver credentials or KMS/SecretStore permissions may have been exposed.
- Whether the current implementation has a tested repair procedure for the identified state.

The current repository deliberately does **not** ship a general repair/re-anchor command. In particular, there is no supported automatic operation that truncates an unanchored suffix, rewrites a JSONL file, or advances the remote checkpoint to the local head. Do not improvise such a command in production.

Before reopening the authority, all ambiguous or unreturned approval grants must be rendered non-consumable. Where the event history cannot conclusively establish whether an approval was issued and retained, require a fresh dual approval after the ledger is restored and verified. An approval that may have been exposed must not be made usable merely because its ciphertext remains in the vault.

If no reviewed, tested repair path applies, keep the authority disabled and preserve the incident bundle for an explicit engineering change. The affected deployment remains in its existing state; audit repair is not permission to change deployment state.

## Post-recovery verification

Before re-enabling even read-only approval diagnostics:

1. Verify the complete local hash chain from genesis.
2. Verify that the local head equals the external checkpoint exactly and the adapter's immutable ledger_id equals the independently configured expected_ledger_id.
3. Verify that the anchor is reading from the intended environment/ledger identity and that its durable CAS/retention guarantees are restored.
4. Review every approval ID in the affected suffix for global uniqueness and ensure any ambiguous grant is rejected/burned or requires fresh dual approval.
5. Verify that restored grant-vault envelopes match their exact audit approval and that claimed/consumed/rejected grants cannot be restored.
6. Run the focused external-anchor, grant-restore and authority integration regressions against the repaired copy before deploying the repaired state.
7. Re-enable the approval service only after the incident owner and a second approver sign off.

No part of this runbook authorizes reconciliation mutation, rollback, selector or active-pointer changes, journal phase changes, reservation release, or runtime lifecycle actions.
