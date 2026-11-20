# External reconciliation audit-head anchoring

## Scope

The local reconciliation audit store already maintains a durable hash-linked JSONL chain and can compare its head with a caller-supplied ReconciliationAuditHead. This document specifies the next trust boundary: an external, durable checkpoint that is not writable through the local audit directory.

The implementation is provider-neutral:

- runtime/deployment_reconciliation_anchored_audit_store.py defines ReconciliationAuditHeadAnchor and ExternallyAnchoredReconciliationAuditStore.
- The production anchor service is deliberately not selected or implemented in this repository.
- The wrapped store remains a DurableReconciliationAuditStore subclass, so it can be injected into the existing ReconciliationApprovalAuthority without changing its audit API.
The wrapper covers the authority's full audit write path: proposal, approval, consumption-start and terminal consumption/rejection events each advance the remote checkpoint. A regression test injects the anchored subclass into ReconciliationApprovalAuthority and verifies all four events are checkpointed in sequence.

## External anchor contract

An adapter must expose one immutable ledger namespace and provide:

- ledger_id -> string: stable opaque identifier for this exact audit ledger, bound to its deployment environment/project namespace;
- read_head() -> ReconciliationAuditHead;
- compare_and_set(expected, replacement) -> bool.

`ExternallyAnchoredReconciliationAuditStore` requires `expected_ledger_id` at construction and compares it exactly with the adapter's immutable `ledger_id`. The adapter identity is checked again before each external-head read. This is a configuration guard; the production adapter must enforce the same ledger ID as the actual remote key/database namespace and must not merely echo a caller-provided value.

The Host configuration must pass the independently provisioned expected_ledger_id into ExternallyAnchoredReconciliationAuditStore. Construction rejects a missing/mismatched identifier, and each remote-head read rechecks that the adapter identity has not changed. The provider adapter must also bind its remote key/database row to this same identifier; echoing a caller-supplied value without enforcing the remote namespace is not sufficient.

The adapter must store its checkpoint outside the writable audit directory, provide durable and linearizable compare-and-set semantics, authenticate the Host, and fail closed when its checkpoint is absent or unavailable. It must not silently initialize or reset a ledger. Production provisioning must explicitly initialize the external checkpoint to sequence 0 with the all-zero digest before the first audit event. The adapter must expose an immutable ledger_id; the wrapper checks the expected identity at construction and on both sides of every remote head read and compare-and-set operation. Any identity drift is a distinct fail-closed condition, not an anchor outage.

A local hash chain is only a tamper-evident sequence. The independent external checkpoint is what detects deletion/rewrite/truncation of the local suffix after the last trusted checkpoint.

## Append and verification protocol

For each event append, including proposal/approval records and the approval-consumption start/finish events, the wrapper:

1. Acquires a same-host coordination lock so multiple local processes cannot interleave the checkpoint protocol.
2. Reads the external checkpoint H.
3. Requires the complete local ledger head to equal H exactly.
4. Appends and fsyncs exactly one local event.
5. Reads/verifies the new local head H+1.
6. Performs external compare-and-set from H to H+1.
7. Rereads the external head and requires exact equality with H+1 before returning success.

Public verify() and events() also require the local head to match the external checkpoint before exposing audit state. The same wrapper covers record(), append(), begin_approval_consumption() and finish_approval_consumption() so approval issuance and one-use claims cannot bypass anchoring when this store is injected into the authority.

For operator diagnostics, inspect_anchor_state() performs a read-only comparison and returns only the ledger ID, local/external heads, a classification (anchored, local_ahead, local_behind, forked, local_invalid, anchor_unavailable, or identity_mismatch), and exception class names. It does not return event payloads or attempt repair/CAS. Normal events() remains fail-closed unless the exact heads match.

## Fail-closed behavior

- External anchor unavailable before append: do not append.
- Local ledger differs from the current external checkpoint: reject all reads/writes; do not auto-adopt local state.
- Local append succeeds but external CAS conflicts/fails: do not truncate or rewrite the local ledger, and do not automatically advance the remote checkpoint. The local ledger is now ahead and subsequent operations remain blocked pending operator investigation.
- CAS response is lost after a possible commit: reread the external head; accept only when it exactly equals the new local head. Otherwise fail closed.
- Local ledger tampering, deletion or suffix truncation: the head comparison fails.
- External anchor reset/rollback: the local head no longer matches and the Host fails closed.

The local-ahead state is intentionally operationally inconvenient. An automatic "repair" that copies a local head into the external anchor could legitimize attacker-injected events. Recovery must verify the event history and remote checkpoint provenance under a documented operator procedure before updating the external anchor.

The operational containment/classification process is documented in [deployment-reconciliation-audit-anchor-recovery-runbook.md](deployment-reconciliation-audit-anchor-recovery-runbook.md). The current repository intentionally has no general re-anchor/truncate repair command; ambiguous grants must be rendered non-consumable before approval service is reopened.

## Deployment limits

The wrapper's coordination lock serializes processes sharing one Host filesystem. It is not a distributed transaction and does not make independent local ledgers multi-host safe. A multi-host deployment must use a shared transactional audit database or centralized append service together with an external trust root; the current wrapper will reject divergent hosts rather than merge their ledgers.
The regression suite exercises this same-Host coordination path with four spawned processes sharing a local ledger and a SQLite compare-and-set test anchor stored outside the ledger directory. The SQLite fake verifies process-level lock/CAS ordering only; it is not a production anchor provider or a multi-host service.

The test anchor is an in-memory fake. It verifies CAS ordering, lost acknowledgements, local tampering, genesis mismatch and fail-closed local-ahead behavior. It is not a durable or secure production anchor. No AWS, Azure, GCP, HSM, database or SaaS provider is selected by this change.

## Authorization boundary

External anchoring adds no authentication, no approval identity provider, and no reconciliation executor. It does not authorize rollback, selector/active-pointer changes, journal phase changes, reservation release or runtime lifecycle mutation. Those controls remain disabled until the actual production IdP, KMS/SecretStore, external audit service and deployment-specific Host trust configuration are provisioned and reviewed.
