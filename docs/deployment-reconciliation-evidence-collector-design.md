# Reconciliation evidence collector: decision-specific design

Status: decision-specific production collector remains design-only; the Host-side operation call receipt ledger is implemented, but no production reconciliation collector is enabled.

This design is the next provider-integration step after the journal-fenced snapshot reader. It deliberately does not implement or simulate a provider operation API. The first concrete target is the repository's existing `docker-local` + Local Docker Router/HAProxy stack, but the collector must not be enabled until each required live source has an authenticated, read-only adapter.


## Implementation update: Host-side provider-call receipt ledger

The repository now implements `runtime/deployment_provider_operation_ledger.py` and wires it into `HostDeploymentReplacementManager`:

- Writable managers lazily create a deterministic sidecar database immediately before the first provider mutation: `<history-stem>.provider-operations.sqlite3`. Constructor, recovery-inventory and operator read-back paths remain read-only and do not create it; managers backed by read-only history never create or write this database.
- `prepare_candidate`, `start_candidate`, `switch_traffic`, `retire_previous` and `abort_candidate` each write a durable `started` receipt before entering the provider method.
- A structured `DeploymentOperationResult` is recorded as `returned`, together with its result status and a digest of a bounded, secret-free response projection. Exceptions and malformed returns become `indeterminate`; duplicate action calls are rejected rather than replayed.
- This sidecar is independent of the replacement journal. A receipt proves only that the Host method call started or returned. It is not a provider-issued operation ID, a provider-side operation inspection, or evidence that an asynchronous external operation is terminal. A crash-left `started` receipt remains ambiguous; `indeterminate` is never promoted.

Acceptance tests cover persistence across reopening, crash ambiguity, duplicate-call rejection, wrong action/provider result binding, private file mode, and manager integration. The ledger is audit/recovery metadata only; the decision-specific evidence collector remains blocked until every required live source has a trusted read-only adapter.

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

## Local Docker operation-inspection capability

`LocalDockerProvider.inspect_operation(...)` now implements the provider-operation inspector contract explicitly and returns `unsupported` for the requested scope/action without issuing Docker commands. This is intentional: Docker container inspection can establish current state for an exact immutable container ID, but the Local Docker integration does not own a durable provider operation resource keyed by the coordinator's application-level `operation_id` and action.

The Host call-receipt sidecar is not consulted by this method. A `returned` Host receipt only establishes that the synchronous provider adapter method returned; it is not a Docker operation ID, an asynchronous operation terminal state, or proof that no delayed side effect remains. Consequently, Local Docker cannot currently satisfy the `provider_operation_inspection` evidence requirement for either reconciliation resolution, and the production collector remains unavailable for this provider. Tests assert the explicit `unsupported` response and verify that no Docker I/O occurs.

## Implementation update: decision-specific evidence collector

The repository now contains `runtime/deployment_reconciliation_evidence_collector.py` with `DecisionSpecificReconciliationEvidenceCollector`. It is a read-only policy adapter over three separately injected capabilities: provider operation inspection, immutable runtime inspection, and Router/HAProxy route read-back.

- The provider operation check runs first and must match the exact provider/project/environment/operation ID and the configured operation source. `abort_candidate` accepts only a terminal `succeeded` or `failed` result; `confirm_previous_retired` requires terminal `succeeded`. `in_progress`, `unknown`, `not_found`, `unavailable`, and `unsupported` all fail closed before runtime or route reads.
- `abort_candidate` requires the exact candidate immutable ID to return `not_found`, the exact previous ID to be verified running+healthy, and the verified live route to resolve to the previous ID.
- `confirm_previous_retired` requires the verified route and candidate to resolve to the exact candidate ID, the candidate to be running+healthy, and the exact previous runtime to remain identity-verifiable in `exited`/`dead` state. An unqualified `not_found` does not count as retirement evidence.
- Every response is normalized and hashed; a Host-injected `ReconciliationEvidenceSourceAuthenticator` must authenticate the source endpoint identity and bind the exact response digest, role, and provider/project/environment scope. A source ID string by itself is not authentication.
- The collector emits only the exact four evidence kinds for the selected resolution. It performs no deployment, selector, journal, active-pointer, or reservation mutation.

The collector tests include positive paths using injected test inspectors, wrong-scope/source rejection, stale/future observations, candidate absence vs unavailable, unhealthy runtime, route mismatch, previous-runtime retirement semantics, and explicit Local Docker `unsupported`. These are policy/unit tests, not a real-Docker proof of the source-authentication adapters.

## Approval binding and repeated reads

The authority previously compared the complete evidence object including generated evidence IDs and read timestamps. That made a real reader's second observation differ even when the normalized source response was unchanged. The canonical evidence digest now binds semantic content — evidence kind, source ID, normalized response digest, and immutable runtime claim — while generated IDs and observation timestamps remain independently validated. Observation freshness and the snapshot read window are still checked on every approval and consumption read.

At approval time the authority replaces caller-supplied evidence with the current trusted reader evidence before computing the challenge/audit binding. At consumption it compares the fresh semantic evidence digest and provenance binding, then rechecks freshness and source trust. This permits unchanged state to survive a timestamp refresh; any change to the response digest, source identity, runtime claim, reader identity, or journal revision still fails closed.

### Current enablement status

This is an implemented generic collector contract, not production Local Docker enablement. `LocalDockerProvider.inspect_operation()` deliberately returns `unsupported`, so the collector stops before Docker runtime and Router reads for that provider. A concrete Host source authenticator and a provider with a real operation-status resource remain necessary before positive production evidence can be issued. The existing production approval authority must remain disabled for Local Docker until those gates are met.

## Local Docker runtime/route source authenticator

The repository now includes `runtime/local_docker_reconciliation_source_authenticator.py` with `LocalDockerReconciliationEvidenceSourceAuthenticator`.

- The Host must pin a full Docker daemon ID in trusted configuration. The authenticator never learns its expected ID from the response being checked.
- Each runtime/route source authentication performs a bounded, fixed-argv, read-only `docker info --format` query through the existing `LocalDockerProvider` command runner. It validates the returned daemon ID, daemon name, server version and Docker root directory; a daemon ID mismatch, malformed result, unavailable CLI/daemon or wrong source ID fails closed.
- The endpoint identity digest binds the pinned daemon ID and the returned daemon metadata. The returned source receipt also binds the exact normalized response digest and provider/project/environment scope supplied by the evidence collector.
- This adapter does not authenticate `provider_operation`; that role is explicitly unsupported for Local Docker. It also does not replace the Host's transport security requirements: access to the Docker Unix socket must be protected by Host OS permissions, or a configured Docker TLS context must authenticate the remote endpoint. The pinned daemon ID is an additional identity check, not a substitute for TLS or local socket ACLs.
- Tests exercise runtime/route role binding, pinned-daemon mismatch, malformed/unavailable Docker info, invalid response types, wrong source/scope, and the exception path without exposing raw daemon errors.

`DeploymentHostRuntime.build_reconciliation_source_authenticator()` provides the Host configuration entry point. It requires the operator-provisioned `AI_TEAM_DOCKER_EXPECTED_DAEMON_ID` environment variable and supplies fixed Host-owned runtime/route source IDs. Constructing the authenticator performs no Docker I/O; the first evidence-source authentication performs the read-only daemon identity query.

`DeploymentHostRuntime.build_reconciliation_snapshot_reader(operation_id)` now composes the configured source authenticator, Local Docker provider inspections, an existing-scope Router read-only adapter (or a fail-closed `not_found` adapter when the registry/state record is absent), the decision-specific collector and the SQLite journal-fenced snapshot reader. It reads only existing Host journal/Router registry records and never creates or adopts a Router scope. Its Local Docker read path stops at the provider-operation inspection gate: the Local Docker operation inspector returns `unsupported` without Docker I/O, so runtime and route probes are not attempted. This is a fail-closed diagnostic integration, not an approval authority or production reconciliation enablement.

Unit tests use injected Docker runners and do not constitute a real Docker daemon/TLS integration test. Local Docker still returns `unsupported` for provider operation inspection, so this Host reader cannot produce a positive reconciliation snapshot until that separate operation-status capability is supplied.

