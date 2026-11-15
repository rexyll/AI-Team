# Deployment Provider Contract

## Scope

`runtime/deployment_provider.py` defines provider-neutral request, artifact,
deployment record, health result and operation result types plus the
`DeploymentProvider` protocol. This is a contract-only milestone: importing it
does not contact Docker or a cloud service and does not execute commands.

## Contract rules

- Every request names its project root, project, environment and version.
  Port mappings and labels are explicit; providers must not infer them.
- Build output is identified by provider, immutable artifact reference,
  version and a lowercase SHA-256 digest. A mutable tag alone is not identity.
- Every deployment record binds provider, environment, version, artifact,
  status, health state and creation time. Host code owns persistence.
- Results distinguish `succeeded`, `failed`, `unavailable` and
  `unsupported`; a missing Docker daemon is not a successful no-op.
- Health checks return an explicit state and timestamp. Unknown or unavailable
  health is never treated as healthy.
- Rollback candidates must be prior running deployments with verified healthy
  status and a content-addressed artifact. The provider must still verify the
  record against its host-owned deployment history before changing state.

## Security boundary

Providers are host-owned. Agent-facing tools may request an operation only
through an explicit host authorization path; Docker socket access is not
delegated to an Agent and is not implemented through arbitrary
`run_command` strings. Provider credentials, daemon handles and raw command
execution remain outside Agent context and task records.

## Planned implementation sequence

1. Contract and model validation (this milestone).
2. Local Docker build/run/inspect/health/stop adapter.
3. Host-owned deployment history and verified rollback.
4. Container-backed E2E and CI, including daemon unavailable, build failure,
   unhealthy deployment and rollback failure.
5. Cloud providers remain separate future adapters; no cloud capability is
   implied by this contract.
