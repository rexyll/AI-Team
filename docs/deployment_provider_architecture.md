# Deployment Provider Contract and Local Docker Adapter

## Scope

- `runtime/deployment_provider.py` defines provider-neutral requests, immutable artifacts, deployment records, health results and operation results.
- `runtime/local_docker_provider.py` implements the first host-owned local Docker provider.
- The provider is not wired to Agent-facing arbitrary command execution. A host application constructs it and controls when its methods may be called.

## Local Docker behavior

### Command boundary

The production `SubprocessDockerRunner` invokes Docker with an argument vector, `shell=False`, a finite timeout and bounded output. It does not use `sudo`, shell interpolation, or an Agent-provided command string. Tests inject a fake `DockerCommandRunner`; unit tests therefore do not require a Docker daemon.

A missing executable or daemon connection failure returns `unavailable`. Build, image verification, container start and stop failures return `failed` unless the daemon itself is unavailable. The provider never converts a failed command into success.

### Build identity

Build requires a project-root `Dockerfile`. The image tag is generated from the explicit project and version. After build, the provider inspects the image and records the immutable local Docker image ID as a lowercase SHA-256 digest. Before deployment, it inspects the tag again and requires the image ID to match the supplied artifact digest; mutable tags are not trusted as identity.

### Runtime and health

Deployment creates a uniquely named container with explicit port mappings and labels, then inspects the full container object. It verifies the immutable 64-character Docker container ID, confirms that the ID returned by `docker run` matches the inspected ID, and requires Docker to report `running`. The host history stores both the human-usable container name and immutable container ID; names alone are not treated as runtime identity because they can be reused. Malformed inspection output or an identity mismatch fails closed. The initial record health is `unknown`; a running container is not proof of application health.

Health checks inspect the full container object and compare its immutable ID with the ID persisted in host history before trusting state or health. A reused container name therefore cannot make a different container appear healthy. Stop performs the same identity check before issuing the stop command, preventing a stale history record from stopping a different container after name reuse. A stopped/non-running container is unhealthy. A Docker `HEALTHCHECK` status of healthy/unhealthy is preserved. Missing HEALTHCHECK, starting state, malformed inspect output or an unclassified state remains unknown; it is never promoted to healthy.

Stop is explicit and bounded by the runner timeout. Rollback intentionally returns `unsupported` in this milestone: accepting an arbitrary prior record is not sufficient. T21.6.3 must add host-owned deployment history and verify the previous deployment is a valid healthy rollback candidate before changing runtime state.

## Security boundary

Providers are host-owned. Agent-facing tools may request an operation only through an explicit host authorization path; Docker socket access is not delegated to an Agent and is not implemented through arbitrary `run_command` strings. Provider credentials, daemon handles and raw command execution remain outside Agent context and task records.

## Verification

Fake-runner tests cover executable/daemon unavailable, build failure, image digest verification, start failure, running-state validation, healthy/unhealthy/unknown health, stop failure and the deliberately unsupported rollback path. These tests validate command orchestration without claiming a real Docker daemon integration. A daemon-backed fixture remains part of the later container E2E milestone.

## Planned implementation sequence

1. Provider-neutral contract and model validation (T21.6.1).
2. Local Docker build/run/inspect/health/stop adapter (T21.6.2).
3. Host-owned deployment history and verified rollback (T21.6.3).
4. Container-backed E2E and CI, including daemon unavailable, build failure, unhealthy deployment and rollback failure (T21.6.4).
5. Cloud providers remain separate future adapters; no cloud capability is implied by this implementation.


## Host-owned deployment history (T21.6.3)

Deployment history belongs to the host runtime and must be stored independently of Agent messages or caller-supplied records. The host history is the authority for selecting a prior deployment. A rollback request may identify an environment, but it must not supply the record that authorizes rollback.

The first T21.6.3 increment introduces a local SQLite history store and a host manager. It persists successful running deployment records, records verified health observations, reloads records after process restart, and selects only earlier records whose persisted state is running, whose health observation is healthy, and whose immutable Docker container ID is present and valid. Legacy records without immutable runtime identity remain readable but are not rollback candidates. Rollback candidates are scoped by provider, environment, and project; records from another project cannot authorize rollback. The SQLite store migrates older databases by adding the nullable project column; legacy rows without project identity are deliberately excluded from project-scoped rollback. Connections are explicitly closed, use a bounded busy timeout for concurrent writers, and the database file is restricted to mode 0600 on POSIX hosts. Corrupt database files and malformed persisted record payloads fail closed; concurrent append behavior is covered by tests. Before delegating rollback, the manager checks provider, environment, and project scope against the configured host provider and request. Provider-specific safe replacement remains a separate requirement: the Docker adapter must not stop the current deployment before it has verified that the target can be started and made healthy. Until that replacement/traffic-switch sequence exists, Docker rollback remains unsupported and the manager must report that honestly.


### Fresh health verification before rollback delegation

Persisted healthy status is historical evidence, not sufficient authorization for a later rollback. Immediately before delegating rollback, HostDeploymentManager calls the configured provider's health_check on the host-loaded candidate. The provider must re-verify its immutable runtime identity and current health. The fresh observation is persisted to host history; only an exactly healthy result permits delegation. unhealthy, unavailable, and unknown observations block rollback and update history. Provider exceptions or inability to persist the observation also block rollback. This check does not make Docker replacement supported: the current Local Docker provider still reports rollback as unsupported, and no traffic-switch/old-instance-retirement sequence is claimed.


## Safe replacement design gate (T21.6.3)

A rollback is a deployment replacement, not a call to `docker run` followed by `docker stop`. The current history model does not yet identify the authoritative active deployment or persist a replacement transaction. Therefore the generic `DeploymentProvider.rollback` method is not, by itself, proof that a provider can safely replace a deployment. HostDeploymentManager currently revalidates the historical candidate and delegates; Local Docker correctly returns `unsupported`.

Before enabling any provider replacement, the following host-owned protocol must be implemented and tested as one transaction:

1. **Resolve both identities:** load the target from host history and resolve exactly one current active deployment in the same provider/environment/project scope. Ambiguous or missing active state blocks replacement.
2. **Prepare candidate:** start the target artifact as a distinct candidate instance on a controlled network. Do not publish host ports or disturb the active instance. Persist a replacement operation ID and immutable candidate runtime identity before proceeding.
3. **Verify candidate:** probe the candidate through a host-only route, requiring fresh `healthy` status and matching immutable runtime identity. Missing health evidence is not success.
4. **Switch traffic:** use an explicitly host-owned traffic router/proxy with an atomic or otherwise verifiable route update. A successful command response alone is insufficient; read back the effective route and verify it targets the candidate.
5. **Retire old instance:** only after route read-back and candidate health confirmation may the old instance be stopped. Persist each phase and resulting identity.
6. **Compensate on failure:** before traffic switch, remove only the candidate and leave the old instance untouched. If route switch is uncertain, do not stop either instance; report a recoverable/ambiguous operation and require reconciliation. If post-switch retirement fails, preserve both instances and report degraded rather than claiming rollback completion.

Required host-history additions before implementation: explicit active/stopped lifecycle transitions, a single-active deployment invariant per scope, replacement-operation journal with phase and immutable identities, idempotent recovery/reconciliation after process crash, and compare-and-swap protection against concurrent replacements. The provider capability must expose prepare, candidate health, route switch/read-back, retire-old, and abort/reconcile operations; a single opaque `rollback()` call is insufficient for the host to enforce ordering.

**No-go conditions:** no controlled candidate network, no host-owned router/proxy, no route read-back, no immutable identities for both instances, no durable operation journal, or concurrent/ambiguous active state. In any of these cases the provider must return `unsupported` or the manager must fail closed. No zero-downtime or safe rollback claim is permitted until a daemon-backed E2E proves both success and injected failures at every phase.


## Granular replacement capability contract (T21.6.3)

`runtime/deployment_replacement.py` now defines a provider capability separate from the legacy opaque `rollback()` method. It specifies explicit phases (`prepared`, `candidate_started`, `candidate_healthy`, `traffic_switched`, `previous_retired`, `aborted`, `needs_reconciliation`) and a persistable journal snapshot containing the target and previous deployment IDs plus immutable runtime identities and the effective route target.

The `DeploymentReplacementProvider` protocol separates candidate preparation/start, candidate health verification, traffic switch, effective-route read-back, old-instance retirement, and candidate abort. Each operation is keyed by a host-generated operation ID and is required to be idempotent. The protocol is declarative only: no provider currently implements it, no journal is yet persisted by `HostDeploymentManager`, and Local Docker rollback remains unsupported. This is a contract milestone, not a claim of working replacement or zero-downtime rollback.

### Host-owned replacement coordinator implementation (2026-11-15)

`runtime/deployment_replacement_manager.py` now implements the generic host-side transaction coordinator for providers that implement the full `DeploymentReplacementProvider` capability. It reserves the provider/project/environment scope in the SQLite replacement journal before provider side effects, verifies the previous active deployment is freshly healthy, prepares and starts a distinct candidate, persists its immutable runtime identity, requires fresh candidate health, switches traffic, and reads the effective route back. Only a read-back matching the candidate immutable runtime permits the active-deployment pointer compare-and-swap. The previous runtime is retired only after that CAS, and the provider must return an inspect-confirmed stopped record whose immutable identity matches the journal before host history is marked stopped.

Before traffic switch, a failed candidate can be aborted only after read-back proves the previous route is still effective; the coordinator then requires an inspect-confirmed stopped candidate record and a second route read-back. If routing is ambiguous, abort/retirement cannot be verified, or an exception occurs after an external side effect, the coordinator preserves both runtimes and leaves the scope reserved as `needs_reconciliation`. It never guesses a rollback route. `tests/test_deployment_replacement_manager.py` exercises the transaction using a fake provider.

This does **not** make Local Docker replacement or rollback available: `LocalDockerProvider` still lacks an isolated candidate network and host-owned traffic router with authoritative route read-back. The manager is a generic orchestration layer, not a real Docker integration. The read-only recovery classifier still performs no automatic provider reconciliation, and no authenticated operator/two-person approval path can release `needs_reconciliation`. No zero-downtime or Docker rollback claim is made.


### Durable replacement journal and concurrency reservation

The host SQLite store now persists replacement journal snapshots in a dedicated `deployment_replacements` table. `begin_replacement()` accepts only the initial `prepared` phase and reserves the provider/project/environment scope. A partial unique index permits at most one non-terminal replacement per scope across host processes; `needs_reconciliation` intentionally remains blocking. Only `previous_retired` and `aborted` release the reservation.

`update_replacement()` uses an expected-phase compare-and-swap update, validates the allowed phase transition, and rejects changes to provider/project/environment, target/previous deployment IDs, creation time, and any immutable runtime/traffic identity already recorded. Journal reads survive store reconstruction. This is durable transaction bookkeeping and mutual exclusion, not yet crash recovery: no provider reconciliation worker or automatic phase resumption is implemented. The active-deployment invariant and Docker traffic router remain future work; Local Docker rollback remains unsupported.


### Explicit active deployment ownership pointer

The SQLite history now has an `active_deployments` table keyed by provider/environment/project, with a globally unique deployment ID. It is deliberately separate from historical `DeploymentRecord.status`: appending a running record does not make it active, and startup does not guess which of multiple historical records owns traffic. `set_active_deployment()` validates that the selected host-history record is running and belongs to the exact scope, then performs an expected-current-ID compare-and-swap inside a SQLite transaction. A single deployment cannot be marked active in two scopes. `active_deployment()` verifies the pointer against the persisted record and fails closed on missing or inconsistent history. `clear_active_deployment()` also requires the expected immutable deployment ID.

This pointer records host-observed traffic ownership only. It is not a liveness check, does not prove that a route is reachable, and must be updated only after an authoritative route switch/read-back (or explicit initial adoption of a known route). Health must still be freshly checked before replacement. Existing databases are migrated by creating the empty table; no active pointer is backfilled from legacy history because that would invent routing state. No Docker traffic router, replacement executor, or automatic crash recovery is implemented; Local Docker rollback remains unsupported.

### Replacement journal implementation status correction

The host SQLite store now implements `begin_replacement`, `update_replacement`, `get_replacement`, and `list_active_replacements`. The initial phase must be `prepared`; a partial unique index reserves each provider/project/environment scope while any operation is non-terminal. Phase changes use expected-phase CAS and a fixed transition graph. Scope, target/previous deployment IDs, operation ID, creation time, and already-recorded runtime/route identities cannot be rewritten. `needs_reconciliation` remains active and blocks a second operation; only `aborted` and `previous_retired` release the reservation. This journal survives host process restart but does not itself resume or reconcile provider operations. No automatic recovery worker or Docker replacement implementation exists.


### Read-only crash-recovery classification

The new `runtime/deployment_recovery.py` module classifies a persisted replacement snapshot into required observations only. Early phases (`prepared` and `candidate_started`) require provider inspection because a crash can occur after an external side effect but before its journal update. `candidate_healthy` requires fresh health and effective-route read-back. `traffic_switched` requires authoritative route read-back confirming the candidate identity before any old-runtime retirement. `needs_reconciliation` requires explicit operator review; terminal phases need no recovery action.

The assessment reports missing immutable runtime identities instead of inferring them, and every result declares `automatic_action="none"`. This is deliberately not a recovery worker: it performs no provider calls, route changes, aborts, retirements, or journal mutations. The scope reservation remains in place for `needs_reconciliation`; Local Docker rollback remains unsupported until a real host-owned router and provider implementation exist.


### Recovery classifier safety boundary

The read-only recovery classifier recognizes only the explicitly supported journal phases. Only `previous_retired` and `aborted` are terminal; an unknown or corrupt phase raises `ValueError` rather than being treated as completed. This is intentionally fail-closed and complements the SQLite partial unique index: every phase other than those two terminal values continues to reserve its provider/project/environment scope.

A `needs_reconciliation` record remains visible in the active-replacement query and blocks a second replacement in the same scope. There is deliberately no operator "unlock" or phase-forcing API. Before adding reconciliation mutations, the host must define operator identity/authentication, append-only audit attribution, the external provider/route evidence required for each resolution, and the applicable approval policy. A note or human decision alone must not release the reservation or assert that a runtime was safely retired.


### Reconciliation authorization and audit design gate

A repository review found three nearby primitives, but none is sufficient authority for deployment reconciliation:

- runtime/scm_provider.py has an in-memory, short-lived, one-use approval bound to an operation, repository and target. Its approved_by value is supplied by the caller; it is attribution text, not authenticated identity. Its process-local state is also not a durable approval/audit record.
- runtime/delivery_audit.py appends JSONL events under a process lock and redacts metadata. It does not authenticate the event actor, provide a tamper-evident chain/signature, or establish that an append is durably committed against power loss. It is useful delivery history, not a security-grade reconciliation ledger.
- security/tool_permission.py is a deny-by-default tool-capability policy. It does not authenticate a human operator or authorize a deployment state transition.

Do not compose these primitives into an unlock path or treat a caller-provided operator string as identity. Before any reconciliation mutation is implemented, the host must provide a trusted authenticated principal (identity established outside Agent-controlled input), and the approval must be short-lived, one-use and bound to the exact provider/project/environment, operation ID, current journal phase, target/previous deployment IDs and immutable runtime identities. The requester and approver must be distinct principals for a scope-releasing decision; approval must be explicit and independently verified by the host. A stale phase, changed identity, expired/replayed approval, missing principal, or failed evidence check must reject without changing the journal.

Every resolution must carry structured, bounded evidence references/summaries from fresh provider inspection and authoritative effective-route read-back. The resolution policy must distinguish aborted from previous_retired: the former requires proof the candidate is absent/contained and the previous runtime remains authoritative; the latter requires proof the candidate is the effective route target and the previous runtime is safely retired. A human note is never evidence of either condition. Audit events must be append-only, actor-attributed from the trusted principal, linked to the exact approval and evidence digest, and persisted before the phase transition; audit failure must leave the reservation intact. The eventual implementation must define tamper detection and durability guarantees rather than assuming ordinary JSONL append is sufficient.

This section is a design gate only. No authenticated operator provider, durable approval authority, reconciliation mutation, manual unlock, provider orchestration or automatic recovery is implemented. needs_reconciliation continues to reserve its scope, and Local Docker rollback remains unsupported.


### Reconciliation contract types (data-only)

`runtime/deployment_reconciliation_contract.py` defines immutable snapshots for a host-authenticated principal, a two-person approval, digest-addressed provider/route evidence, and a reconciliation proposal. The proposal binds the approval to the exact `needs_reconciliation` journal scope, operation ID, deployment IDs and immutable runtime IDs. It accepts only two proposed resolutions: `abort_candidate` (candidate absence, previous runtime inspection and previous-route read-back) or `confirm_previous_retired` (candidate-route read-back, candidate health and previous-runtime retirement), each with provider-operation inspection. Evidence must be uniquely identified, SHA-256 addressed, timezone-stamped and tied to the expected runtime where applicable.

These are validation/data contracts, not a security boundary: constructing `AuthenticatedPrincipal` does not authenticate anyone; the host must verify the identity assertion, approval issuance/expiry/one-use state, evidence source authenticity and freshness. No token authority, durable approval store, audit writer, journal mutation, provider call or reservation release is implemented. A validated proposal is not permission to execute it.


### Reconciliation audit envelope (data-only)

`runtime/deployment_reconciliation_audit.py` defines an immutable audit envelope with a canonical JSON payload, SHA-256 event digest, monotonically increasing sequence number, previous-event digest, trusted-principal snapshot, exact reconciliation scope and runtime identities, approval ID, proposal digest, evidence digest, action and timezone-aware recording timestamp. The envelope validates its own digest; `verify_successor_of()` checks sequence continuity and the previous-event link.

This is only a serialization/integrity contract. It does not append or persist events, authenticate the actor, issue or consume approvals, sign records, anchor a trusted chain head, or mutate the replacement journal. An unkeyed hash chain detects payload edits and broken links only when the expected chain head is protected independently; an attacker able to rewrite the entire store can recompute the chain. It is not a tamper-proof ledger or a durability guarantee. A future host-owned writer must define protected head anchoring, key custody/signatures or equivalent external integrity, append ordering, fsync/transaction semantics, crash recovery, and the rule that the audit commit completes before any journal phase transition. Until then, reconciliation remains data-only and `needs_reconciliation` continues to reserve the scope.


### Audit persistence ordering and transaction design decision

The current SQLite history store opens and commits its own transaction per method, while the existing delivery audit writer is a separate JSONL file that flushes userspace buffers but does not call `fsync`. Neither can currently provide an atomic audit-plus-journal transition. Writing an audit event first and updating the journal in a second transaction is fail-safe with respect to an unaudited transition (a crash can leave an orphan audit intent), but it creates an ambiguous retry window and requires event-ID idempotency and reconciliation of pending audit records.

Before implementing a writer, choose and test one explicit persistence design:

1. **Preferred single-database transaction:** store the reconciliation audit event and perform the expected-phase journal CAS through the same SQLite connection and transaction. Either both commit or neither commits. Enforce unique event IDs and unique sequence numbers, verify the prior chain head inside the transaction, and reject stale journal phase/identity before commit. Configure and document SQLite journal/synchronous settings for the required failure model; a successful SQL commit is not automatically protection against disk/controller failure or malicious database rewriting.
2. **External append-only ledger:** if audit must be independent of the journal database, require an idempotent append API with a durable commit receipt and a defined recovery protocol for the crash window between audit append and journal CAS. A plain JSONL flush or unanchored hash chain is insufficient.
3. **Integrity anchor:** for tamper evidence against an attacker who can rewrite the local database, anchor the latest digest outside that trust domain (for example a host-protected signing key or external append-only service). Key custody, rotation, verification and unavailable-anchor behavior must be specified. A hash chain whose events and head are all stored in the same writable database only detects accidental edits when a trusted expected head is available.

The present milestone deliberately adds no audit database table, writer, transaction coupling, signing dependency or mutation API. The host still lacks a verified operator-authentication adapter and a durable, independently consumed two-person approval authority. Until those trust roots and the crash/failure model are implemented and tested, do not add a reconciliation operation that changes `needs_reconciliation`.
