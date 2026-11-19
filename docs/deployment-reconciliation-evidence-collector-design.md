# Reconciliation evidence collector: decision-specific design

Status: implementation design and acceptance contract; no production collector is claimed by this document.

This design is the next provider-integration step after the journal-fenced snapshot reader. It deliberately does not implement or simulate a provider operation API. The first concrete target is the repository's existing `docker-local` + Local Docker Router/HAProxy stack, but the collector must not be enabled until each required live source has an authenticated, read-only adapter.

## 1. Existing primitives and their limits

The repository already has these building blocks:

- `LocalDockerProvider.inspect_runtime_identity(deployment_id, runtime_id)` inspects an exact immutable Docker container ID and separates identity verification, runtime state and health.
- `DeploymentTrafficReadback` represents Router registry, live selector, effective immutable runtime ID, route generation and selected HAProxy backend endpoint/readiness observations.
- `HAProxyRuntimeAPIClient` only accepts typed allowlisted Runtime API commands; read commands include selector/stat/server-state inspection.
- `DeploymentHistoryReconciliationSnapshotReader` fences evidence collection with two reads of the same SQLite replacement journal.

These primitives are not themselves a reconciliation evidence collector. In particular, the operator-facing `manual_reconciliation_readback` requires both old and candidate runtimes to be running and healthy. That is useful for its diagnostic classification but is incompatible with the two resolution-specific proofs below: abort requires candidate absence, while retirement confirmation requires previous-runtime retirement. Do not reuse that aggregate assessment as either resolution's evidence.

## 2. Decision-specific positive evidence

All reads are scoped to one exact `ReplacementJournalRecord` in `needs_reconciliation`. The collector must use the journal's immutable candidate and previous runtime IDs; mutable container names, labels, deployment names, endpoint addresses or cached inventory are never identity substitutes.

### `abort_candidate`

All of the following are required:

1. **Provider operation inspection**: an authenticated provider-side operation inspection for this exact `operation_id` returns a terminal state proving no create/start/replace operation remains in flight. The journal phase alone is not provider-operation evidence.
2. **Candidate absence**: an authenticated Docker/provider lookup of the exact `candidate_runtime_id` returns authoritative not-found. A timeout, daemon disconnect, malformed response or name-based lookup is unavailable/invalid, never absence.
3. **Previous runtime inspection**: the exact `previous_runtime_id` is identity-verified, running and healthy.
4. **Previous route read-back**: Router runtime identity is verified; durable Router registry and live selector agree; effective target equals the exact `previous_runtime_id`; all selected HAProxy backend endpoints match and are UP/enabled.

### `confirm_previous_retired`

All of the following are required:

1. **Provider operation inspection**: an authenticated provider-side operation inspection for this exact `operation_id` returns a terminal state proving retirement completed and no conflicting provider operation remains in flight.
2. **Candidate route read-back**: Router runtime identity is verified; durable registry and live selector agree; effective target equals the exact `candidate_runtime_id`; selected HAProxy backend endpoints match and are UP/enabled.
3. **Candidate health**: the exact `candidate_runtime_id` is identity-verified, running and healthy from a fresh provider inspection.
4. **Previous runtime retirement**: an authenticated lookup of the exact `previous_runtime_id` proves it is stopped/removed according to the provider's documented retirement semantics. A lookup failure or an unqualified not-found response is not sufficient unless the provider adapter can prove that the queried immutable identity belongs to the expected provider/tenant and that not-found is authoritative.

The two policies are intentionally asymmetric. Do not require the candidate to be absent for retirement confirmation, and do not require the candidate to be healthy/routed for abort. Never infer a positive state from a missing history record.

## 3. Provider operation inspection is a separate capability

The current `DeploymentReplacementProvider` exposes imperative calls such as `abort_candidate` and `retire_previous`, but no read-only `inspect_operation(operation_id)` contract. A journal phase or a previously returned `DeploymentOperationResult` cannot prove the provider's current operation state after a process crash.

Before enabling the production collector, add a provider-neutral read-only operation inspection contract with:

- exact provider, project, environment and `operation_id` binding;
- a provider-issued immutable operation identity (or an explicit documented `not_supported` result);
- explicit state taxonomy distinguishing terminal success, terminal failure, in-progress, unknown, not-found and unavailable;
- observation timestamp and canonical response digest;
- authenticated endpoint/daemon identity and bounded timeout;
- no retries that can mutate provider state.

For Local Docker, Docker itself has no general durable operation resource for the coordinator's application-level replacement ID. The adapter therefore needs an explicit Host-owned operation receipt/ledger written around each provider call, or it must return `unsupported` and block reconciliation. It must not reconstruct a supposedly terminal operation from the replacement journal.

## 4. Evidence construction and source trust

For each successful read, the collector computes the SHA-256 digest over a canonical serialization of the complete validated response, not over a status string or caller-provided digest. Each `ReconciliationEvidence` item records:

- a unique evidence ID;
- the exact required evidence kind and configured source identifier;
- a timezone-aware observation timestamp;
- the canonical response digest;
- `subject_runtime_id` for a runtime being inspected/absent/retired;
- `observed_runtime_id` for the effective route target.

Source authentication belongs to the Host adapter: Docker daemon endpoint and TLS/socket identity, Router immutable container ID, and the HAProxy admin socket inside that exact Router. An allowlisted source name is not authentication. The collector must reject a response if its provider/project/environment/operation scope differs from the journal.

The collector returns only the exact four evidence kinds required for the selected operation. It must reject duplicate IDs, duplicate kinds, missing kinds, unexpected kinds, stale/future timestamps, identity mismatches, unhealthy runtimes, route-generation inconsistencies and any source error. The snapshot reader then performs its second journal read and rejects a changed revision.

## 5. Required test matrix before production enablement

Tests must exercise both positive decisions and fail-closed variants:

| Dimension | `abort_candidate` positive case | `confirm_previous_retired` positive case |
|---|---|---|
| Provider operation | terminal/no operation in flight | terminal/retirement complete |
| Candidate | exact immutable ID authoritatively absent | exact immutable ID verified running + healthy |
| Previous | exact immutable ID running + healthy | exact immutable ID stopped/removed under documented semantics |
| Effective route | exact previous runtime | exact candidate runtime |
| Router/backend | registry = live selector; exact endpoint rows UP | registry = live selector; exact endpoint rows UP |

For each source, test timeout, authentication failure, wrong tenant/scope, malformed response, stale/future timestamp, identity mismatch, and response mutation between repeated reads. Also test that a changed SQLite journal revision invalidates the entire collected set; no partial evidence may escape.

The integration suite must use a disposable real Docker Engine and the real Local Docker Router/HAProxy Runtime API. Mock-only tests establish parser and policy behavior but do not count as production-source evidence. No test may issue a deployment mutation, alter the active selector, update the active pointer, transition the journal, stop a runtime or release the scope reservation.

## 6. Enablement gate

Do not construct a `ReconciliationEvidenceCollector` from `DeploymentHostRuntime.inspect_manual_reconciliation_readback()` by mapping its aggregate assessment into evidence kinds. That path has different preconditions and does not provide provider-operation terminal proof.

Production enablement requires all of:
- a concrete read-only provider operation inspector;
- authenticated exact-ID runtime inspectors;
- authenticated Router/HAProxy route read-back;
- operation-specific evidence policy and integration tests;
- Host-configured source identities and freshness limits.

Until then, the existing reader remains a journal-fencing adapter around an injected collector, and the approval authority must remain unavailable to production callers. No IdP, KMS, distributed claim store or deployment mutation is selected by this design.
