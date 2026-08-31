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
`[x] 15.5` Security regression suite

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
- [x] Fence Developer task/dependency/feedback/result/history/metadata/review-round fields at the Developer tool-loop model boundary.
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
- [x] Expand cross-boundary regression coverage for security-policy bypass attempts introduced by observability boundaries.
- [x] Full security regression verification.

# Phase 16 — Observability / Operations

### 16.1 Structured logging — completed
- [x] Provider-independent structured logger
- [x] Deterministic JSON-safe log records
- [x] Secret redaction at logging boundary
- [x] Severity helpers
- [x] Regression coverage

### 16.2 Metrics — completed
- [x] Provider-independent metrics registry
- [x] Counters, gauges, histograms
- [x] Thread-safe aggregation
- [x] Low-cardinality labels
- [x] Workflow event metrics
- [x] LLM / tool / reviewer metrics coverage
- [x] Regression coverage

### 16.3 Tracing — completed
- [x] Provider-independent `Tracer` / `TraceSpan` primitives
- [x] `trace_id`, `span_id`, and `parent_span_id` lineage
- [x] Context-local current span via `ContextVar`
- [x] Duration and success/error status capture
- [x] Secret-safe, JSON-safe span attributes
- [x] Detached snapshot/export contract
- [x] Explicit parent / trace-id support
- [x] Concurrency isolation regression coverage
- [x] Instrument every concrete Agent.run as a `workflow.stage.<role>` span with `task_id`, role, stage, and result status
- [x] Instrument BaseAgent LLM calls as child spans of the active agent stage
- [x] Instrument authorized tool execution as a child span of the active agent stage
- [x] Add lifecycle regression coverage for Agent → LLM and Agent → Tool trace lineage
- [x] Add an explicit workflow/task root span around `TaskWorkflow.execute`
- [x] Correlate tracing with structured logs and metrics
- [x] Full observability regression verification

### 16.4 Operational Dashboard — completed
- [x] Define a provider-independent dashboard read model
- [x] Aggregate project/task/workflow status from authoritative runtime data
- [x] Aggregate Developer / Tester / Reviewer operational statistics
- [x] Expose workflow duration, throughput, failure, retry, and recovery summaries
- [x] Expose LLM/tool/reviewer telemetry summaries without copying raw trace payloads
- [x] Link task summaries to `trace_id` / root span identity
- [x] Preserve low-cardinality Metrics semantics; never use `trace_id` / `span_id` as metric labels
- [x] Add dashboard read-model contract tests
- [x] Add empty-state and multi-task aggregation tests
- [x] Add Event → Log → Metrics → Trace correlation tests
- [x] Expose a stable CLI/API read interface
- [x] Add dependency-free operational dashboard UI renderer
- [x] Add dashboard HTML export entry point
- [x] Add dashboard UI rendering/export contract tests
- [x] Integrate dashboard export into the primary CLI
- [x] Add CLI/dashboard integration contract tests
- [x] Full Phase 16.4 regression verification

### 16.5 Alerting — completed
- [x] Define alertable operational conditions foundation
- [x] Failure-rate threshold rule
- [x] Latency threshold rule
- [x] Retry threshold rule
- [x] Reviewer rejection / recovery alerts
- [x] Tool-loop anomaly alert rules
- [x] Expose bounded tool-loop telemetry through the dashboard read model
- [x] Alert deduplication and cooldown semantics
- [x] Provider-independent alert interface
- [x] Alert rule / cooldown regression tests
- [x] Full Phase 16.5 regression verification

### 16.6 Alert delivery — completed
- [x] Provider-independent alert sink interface
- [x] Structured alert event emission
- [x] Console / log sink
- [x] Webhook sink with network-egress enforcement
- [x] Delivery retry / failure semantics
- [x] Alert delivery observability
- [x] Alert delivery regression tests
- [x] Full Phase 16.6 regression verification

# Phase 17 — Developer Experience

### 17.1 CLI — completed
- [x] Preserve the existing human-readable CLI execution flow
- [x] Preserve `--projects-base` workspace selection
- [x] Preserve `--dashboard` HTML export integration
- [x] Define stable machine-readable `--output json` mode
- [x] Serialize project result through the canonical `ProjectResult.to_dict()` contract
- [x] Include stable task identity/status/role/title/error fields in JSON output
- [x] Add CLI parser and JSON-output regression coverage
- [x] Full Phase 17.1 regression verification

### 17.2 Configuration — completed
- [x] Define a stable configuration contract
- [x] Provider/model configuration validation
- [x] CLI/environment precedence rules
- [x] Configuration regression tests
- [x] Documentation
- [x] Full Phase 17.2 regression verification

### 17.3 Plugin API — completed
- [x] Define extension points and lifecycle
- [x] Versioned plugin contract
- [x] Capability/security boundary for plugins
- [x] Plugin regression tests
- [x] Documentation
- [x] Full Phase 17.3 regression verification

### 17.4 Documentation — completed
- [x] Align README/user guide/version references with current runtime
- [x] CLI reference
- [x] Configuration reference
- [x] Extension/plugin guide
- [x] Operational troubleshooting guide

### 17.5 Example projects — completed
- [x] Minimal deterministic example
- [x] Example with tests and review loop
- [x] Example demonstrating workspace isolation
- [x] Example demonstrating operational dashboard/alerts
- [x] Example documentation

## Phase 17 acceptance
All Phase 17 developer-experience contracts and examples are implemented and covered by the full regression suite. The current development branch is the accepted working branch for these changes.

## Next planning gate
Phase 17.5 is the final node currently defined in this development plan. Any Phase 18 work should be planned from a fresh repository-state review rather than inferred or silently added to this plan.
