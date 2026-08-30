# AI-Team Development Plan

## Phase 14 — Reliability / Delivery Semantics

### 14.4 Cross-process fencing
- [x] OS-level per-task process locking
- [x] Lease acquire / renew / release / owner fencing
- [x] Result commit ownership boundary
- [x] Independent-process regression coverage
- [x] Local full-suite verification

### 14.5 Exactly-once / At-least-once semantics
- [x] Explicitly define execution vs delivery semantics
- [x] Stable task-attempt-delivery idempotency key
- [x] Durable deduplication of committed deliveries
- [x] Duplicate delivery must not re-apply result
- [x] Retry remains at-least-once at execution layer
- [x] Crash-after-apply / before-ack recovery state
- [x] Explicit processing recovery / takeover policy
- [x] Cross-process duplicate reservation regression tests
- [x] Connect delivery identity to the real Task result persistence boundary
- [x] Add authoritative sink reconciliation contract
- [x] Add durable audit / observability for delivery transitions
- [x] Complete cross-process crash / retry integration
- [x] Full regression verification

## Design rule
Execution is intentionally **at-least-once**: retries and crash recovery may execute a logical attempt more than once. Result delivery is **idempotent at the durable commit boundary**: repeated delivery of the same stable delivery identity must not mutate task state more than once.

A `processing` delivery is ambiguous after a crash. AI-Team must not infer success or failure from process liveness, timestamps, or the marker itself. Recovery must first reconcile with an authoritative durable sink, then explicitly choose `commit` when the mutation is known to have happened or `retry` when it is known not to have happened.

A generic Python callback cannot by itself provide globally exactly-once effects. True exactly-once effect requires the business mutation and delivery record to share a transaction or the target sink to provide an equivalent idempotency guarantee.

# Phase 15 — Security Hardening

`[x] 15.1` Package / dependency policy
`[x] 15.2` Network egress policy
`[x] 15.3` Secret isolation
`[x] 15.4` Prompt injection resistance
`[ ] 15.5` Security regression suite

## 15.1 Dependency policy
Runtime dependencies must be explicitly declared in `requirements.txt`, use exact `==` version pins, and be declared only once. The policy is enforced by `security.dependency_policy` and its regression tests.

## 15.2 Network egress policy
Network access is deny-by-default and requires HTTPS plus an explicitly authorized hostname. Network operations must pass through the enforcement boundary before execution; rejected destinations must never invoke the underlying operation.

## 15.3 Secret isolation
Secrets are redacted at agent context, tool execution record, durable result, and delivery audit boundaries. End-to-end regression coverage verifies that common API keys, tokens, passwords, authorization values, and credentials cannot cross these observable/persistent boundaries.

## 15.4 Prompt injection resistance — completed
The model must treat task descriptions, dependency outputs, tool results, repository files, test output, and agent feedback as **untrusted data**, not as instructions that can override the system policy or tool permissions.

Completed in previous increments:
- [x] Define the reusable untrusted-content boundary helper in `security.prompt_injection`.
- [x] Add canonical `<untrusted-data source="...">` fencing with application-controlled provenance labels.
- [x] Add regression coverage for hostile text, structured tool results, invalid labels, fence-breaking labels, and authoritative system trust policy.

Completed in this increment:
- [x] Fence Architect task, dependency, result, history, and metadata fields at the model-facing prompt boundary.
- [x] Fence Tester task and Developer-result fields at the model-facing prompt boundary.
- [x] Fence Reviewer task, Developer result, Tester feedback, Reviewer feedback, dependency context, history, metadata, and review-round fields at the model-facing prompt boundary.
- [x] Fence tool-produced content centrally in `BaseAgent` before it is sent back to the model, without mutating runtime/audit messages.
- [x] Fence Developer task/dependency/feedback/result/history/metadata/review-round fields at the tool-loop model boundary.
- [x] Fence Developer tool-loop checkpoints before they are returned to the model.
- [x] Keep runtime capability authorization independent from model-provided or untrusted content.
- [x] Add adversarial Developer regression coverage for hostile task data, dependency context, tester/reviewer feedback, tool results, and checkpoint content.
- [x] Verify legitimate Developer execution requirements remain outside the untrusted-data fencing.
- [x] Make prompt-injection attempts observable in workflow execution/audit events using rule/source/count metadata only; never persist inspected raw content.
- [x] Add end-to-end evidence that injection attempts cannot alter actual workspace scope or tool-guard decisions.
- [x] Consolidate prompt-injection defenses into the Phase 15.5 security regression suite runner.

## 15.5 Security regression suite
Current completed coverage includes strict evidence-gate provenance validation and workflow evidence-lineage regression coverage. In particular, gate validation remains fail-closed when explicit provenance is missing; isolated workflow transition-contract compatibility must not synthesize provenance inside the generic evidence validator.

Implemented in this increment:
- [x] Add a deterministic security regression runner covering dependency, egress, secret-isolation, prompt-injection, workspace/tool-security, and evidence-gate tests.
- [x] Document the security regression command and boundary expectations in `SECURITY.md`.

Remaining:
- [ ] Add/expand cross-boundary regression coverage for security-policy bypass attempts as new boundaries are introduced.
- [ ] Full security regression verification after the consolidated runner is pulled locally.

# Phase 16 — Observability / Operations

`[ ] 16.1` Structured logging
`[ ] 16.2` Metrics
`[ ] 16.3` Tracing
`[ ] 16.4` Operational dashboard
`[ ] 16.5` Alerting

# Phase 17 — Developer Experience

`[ ] 17.1` CLI
`[ ] 17.2` Configuration
`[ ] 17.3` Plugin API
`[ ] 17.4` Documentation
`[ ] 17.5` Example projects
