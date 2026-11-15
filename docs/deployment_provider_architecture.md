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
