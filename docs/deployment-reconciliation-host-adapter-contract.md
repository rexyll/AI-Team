# Deployment reconciliation Host adapter contract

Status: provider-neutral contract implemented; concrete production adapters remain unconfigured.

This document defines the trust boundary around two-person deployment reconciliation. It does not select an identity provider, authenticate a real person, inspect a live provider, or authorize a deployment mutation.

## 1. Security boundary

The Host owns all identity-provider credentials, provider API credentials, journal access, evidence collection, approval grants, and audit persistence. Agents and callers may submit a proposal and an opaque authentication response, but they cannot supply the current snapshot used at consumption or override the authenticated principal.

The current implementation deliberately has no default IdP adapter and no default snapshot reader. A `HostAuthenticator` and a `ReconciliationSnapshotReader` must be injected. A fake adapter is suitable for tests only and is not production authentication.

## 2. HostAuthenticator requirements

The authority issues a separate `HostAuthenticationChallenge` for the requester and approver. Each challenge binds:

- A cryptographically random nonce and unique challenge ID.
- The configured audience.
- The purpose (`requester` or `approver`).
- The exact reconciliation operation and proposal-scope digest.
- Issuance and expiry times.
- For the approver challenge, the requester issuer and subject.

A concrete IdP adapter must validate the actual provider proof before returning `VerifiedHostAuthentication`. At minimum it must:

1. Verify the signature or credential cryptographically using trusted keys/credentials and a strict algorithm policy.
2. Enforce the exact configured issuer and audience; validate expiry, issuance/authentication time and any required authentication-strength policy.
3. Bind the proof to the exact challenge nonce, purpose, operation and proposal digest; reject replayed, expired, cross-audience or cross-operation proofs.
4. For the approver, verify the requester binding and return the immutable issuer/subject identity from the verified provider proof.
5. Map only provider-verified subject, issuer, authentication method and authentication time into `AuthenticatedPrincipal`; never trust caller-supplied username, role, issuer, method or timestamp.

For an OIDC adapter, the implementation must additionally define discovery/JWKS refresh, key rotation, issuer/audience handling, allowed signing algorithms, nonce validation, `exp`/`iat`/`auth_time`, and the required `acr`/`amr` policy. For a WebAuthn adapter, it must define RP ID, allowed origins, challenge, user-presence/user-verification policy, credential ownership and signature-counter/replay handling. These are provider-specific implementations and must not be simulated by a generic receipt constructor.

`VerifiedHostAuthentication` is an assertion from the injected trusted adapter, not a self-authenticating token. The authority independently compares every returned binding with the challenge it issued. The adapter implementation and its configuration therefore remain inside the Host trust boundary.

## 3. ReconciliationSnapshotReader requirements

The current-snapshot reader must obtain the journal and all required observations from trusted live sources. It must not accept a snapshot supplied by the caller, use stale caches, infer runtime identity from mutable names, or convert an unavailable/unknown read into positive evidence.

The provider-neutral consistency strategy is a journal-revision fence:

1. Read the durable journal and obtain its opaque revision (R_1).
2. Read the required provider, runtime and traffic-route observations using the exact immutable runtime IDs from that journal.
3. Validate each source response, scope, status, identity and timestamp. Canonicalize the evidence and compute the record/evidence digests.
4. Reread the journal revision (R_2). Require (R_2 = R_1); otherwise discard the whole snapshot and fail closed.
5. Return `ReconciliationCurrentSnapshot` with a `ReconciliationSnapshotReadReceipt` containing the reader ID, operation ID, snapshot ID, (R_1/R_2), record/evidence digests, exact evidence-source set and read start/completion times.

This is an optimistic journal consistency fence. It is **not** a claim that independent Docker, Router/HAProxy or cloud-provider APIs participate in one distributed transaction. Each external observation remains timestamped and must satisfy the configured freshness window. A concrete adapter must document its source-specific read semantics and residual race window.

### Required evidence mapping

The contract requires the following exact evidence kinds for each resolution:

| Resolution | Required evidence |
|---|---|
| `abort_candidate` | `provider_operation_inspection`, `candidate_absence`, `previous_runtime_inspection`, `previous_route_readback` |
| `confirm_previous_retired` | `provider_operation_inspection`, `candidate_route_readback`, `candidate_health`, `previous_runtime_retirement` |

Every evidence item must have a unique ID, an allowlisted source name, an observation timestamp and a SHA-256 digest. Runtime evidence must identify the exact expected immutable runtime ID. Route evidence must identify the actual observed immutable runtime ID. A `not_found`, timeout, invalid response, identity mismatch or unavailable source is not positive evidence.

The source allowlist identifies configured Host sources; it does not, by itself, authenticate those sources. The concrete reader must authenticate the underlying endpoint/daemon, validate the response and compute the digest over a canonical representation of the observed data.

## 4. Snapshot receipt validation

At approval time, `authorize_proposal()` performs a fresh read through the injected
trusted reader before creating either authentication challenge. It compares the
reader's exact journal record and evidence digest with the proposed values, validates
the reader/source allowlists and timestamps, then replaces any proposal-supplied
receipt with the receipt returned by that trusted read. At consumption time it
performs another fresh read and requires the same stable provenance binding. A
caller-created receipt is never accepted as a substitute for the reader call.

The current contract verifies:

- The reader ID is in `trusted_snapshot_readers`.
- Every evidence source is in `trusted_evidence_sources`.
- The receipt operation ID, journal digest, evidence digest and source set match the supplied snapshot exactly.
- The journal revision is unchanged between the two journal reads.
- The read completed in the past, is within the freshness window, and did not exceed the configured consistency-window duration.
- The approval digest binds the reader ID, operation ID, journal revision, record/evidence digests, evidence-source set and consistency model.

Snapshot IDs and read timestamps identify an individual read and are expected to change on reread. The stable approval binding therefore covers reader and revision identity rather than requiring the second read to reuse the first read's snapshot ID.

The receipt is an internal trusted-reader assertion, **not a digital signature**. Its integrity depends on injection of the intended Host reader, protected reader configuration, authenticated source calls and the allowlists configured by the Host.

## 5. Failure policy and non-goals

Any missing receipt, untrusted reader/source, changed journal revision, changed evidence digest, stale/future timestamp, long read window or source error fails closed before approval or consumption. If a consumption claim has already been durably started, a later validation failure is finalized as rejected where possible; a process crash leaves the claim fenced and requires fresh dual approval.

This contract adds no deployment provider mutation, rollback, journal phase transition, active-pointer update, Router selector update or runtime lifecycle action. Consuming an approval returns an approved proposal; it does not execute it.

## 6. Production integration still required

The repository currently contains no configured production IdP, no production `HostAuthenticator`, and no production `ReconciliationSnapshotReader` implementing the mapping above. Before production use:

- Select the organization's actual IdP and implement its provider-specific proof validation.
- Select and document the durable journal, provider inspection and traffic-route sources; implement the revision fence and required evidence mapping against them.
- Protect a restorable bearer grant outside the audit ledger with the Host's KMS/SecretStore; the ledger intentionally stores only the token digest.
- For multi-host Hosts, replace the same-host file-lock claim path with a transactional shared database/unique constraint or centralized approval service.
- Anchor the audit head in an external trusted system and define remote retention.

No provider-specific secrets, issuer URLs, client IDs or credentials should be committed to this repository. Until these integrations and deployment-specific trust configuration exist, the code is a tested security contract, not production identity or evidence verification.
