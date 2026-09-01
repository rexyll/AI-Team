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
- [x] Workflow event metrics
- [x] LLM / tool / reviewer metrics coverage
- [x] Regression coverage

### 16.3 Tracing — completed
- [x] Provider-independent `Tracer` / `TraceSpan` primitives
- [x] `trace_id`, `span_id`, and `parent_span_id` lineage
- [x] Context-local current span via `ContextVar`
- [x] Duration and success/error status capture
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

# Phase 18 — Production Architecture Consolidation

Phase 18 is a fresh repository-state-driven hardening phase. It must not introduce parallel runtime implementations merely to satisfy examples or tests. New abstractions must consolidate existing production boundaries and preserve backward compatibility unless a contract explicitly requires a breaking change.

### 18.1 Canonical Tool Invocation Boundary — completed
- [x] Review existing `ToolInvocationService` as the current authorization/execution boundary
- [x] Confirm `DeveloperToolInvocationAdapter` remains a thin compatibility adapter
- [x] Introduce a canonical immutable tool invocation request contract
- [x] Make single and batch invocation share the same request validation path
- [x] Preserve capability, permission, argument-validation, audit, and tracing boundaries
- [x] Add contract tests for single/batch/concurrent equivalence
- [x] Remove duplicated invocation-shape semantics from agent-facing code
- [x] Keep mutation/read-only cache decisions outside the authorization boundary
- [x] Full 18.1 regression verification

### 18.2 Runtime State / Persistence Consistency — completed
- [x] Audit authoritative state owners and compatibility wrappers
- [x] Define a canonical `TaskStateStore` snapshot contract
- [x] Make in-memory task-state persistence support atomic batch snapshots
- [x] Align `AtomicTaskStateStore` with the canonical task-state contract
- [x] Verify recovery/replay semantics against current event projection
- [x] Verify lease/recovery state transitions against task lifecycle
- [x] Add cross-boundary consistency contracts to the full regression suite
- [x] Full regression verification

The local full-suite verification for this phase passed after the recovery/projection consistency corrections; subsequent focused recovery contracts are required to remain green in future regressions.

### 18.3 Performance / Tool-loop Efficiency — in progress
- [x] Establish deterministic performance baselines from existing telemetry
- [x] Identify remaining duplicate tool execution and unnecessary LLM turns
- [x] Improve only evidence-backed bottlenecks
- [ ] Preserve correctness and security boundaries while optimizing
- [x] Add regression thresholds

Current evidence baseline from the existing real-Developer telemetry includes a serial 1-developer / 4-task sample with 14 LLM calls, 31 tool calls, 28 unique tool calls, 3 duplicate tool calls, 0 retry tool calls, 51,599 input tokens, 1,636 output tokens, 45,908 tool-result characters, and approximately 99.2% LLM-time ratio. This identifies duplicate tool execution and LLM-dominant latency as optimization candidates; it does not by itself prove that any specific LLM turn is unnecessary.

The benchmark layer now exposes deterministic snapshot fields and evidence-based efficiency findings, while regression gates accept an explicit relative cost tolerance without weakening the default zero-increase policy.

Exact-duplicate analysis is separated from failure-recovery retry analysis. Only calls classified as `exact_duplicate` are treated as direct duplicate-execution optimization candidates; required failure-recovery retries remain correctness-sensitive and are not counted as wasted exploration. Legacy metric-only benchmark results continue to support the older aggregate duplicate counter as a coarse compatibility signal.

A cache-probe diagnostic distinguishes a genuine duplicate tool call from repeated cache inspection. When per-call category telemetry is available, `cache_probe_excess = max(0, cache_hits - exact_duplicate_tool_calls)` identifies possible duplicate cache probing without changing runtime behavior.

A side-effect-free `ToolResultCache.contains()` probe is now available for preflight decisions. It does not change hit/miss counters, LRU recency, or cached values. The Developer loop has been switched to use this probe for safe-batch preflight after real benchmark telemetry demonstrated redundant cache probing; controlled A/B validation remains required because earlier live samples were invalid.

The real-Developer benchmark now preserves Developer decision traces through Executor → task metrics → aggregate benchmark results. A/B comparison reports include LLM-call, duration, token, exact-duplicate, cache-probe, and decision-trace deltas plus decision-reason counts. This provides the evidence surface required before changing the Developer loop for performance.

The live benchmark fixture was corrected to create isolated temporary workspaces under the authorized `projects/` sandbox root rather than the operating-system temp directory. This keeps filesystem isolation intact while allowing the terminal workspace policy to execute real verification commands. A failed live sample with `sample_valid=False` must not be used as performance evidence.

Live benchmark runs then exposed an upstream OpenAI-compatible tool-continuation failure (`No user query found in messages`) in both baseline and candidate. A narrow Agnes-only continuation adapter was tested, but live A/B evidence showed that synthetic continuation prompts can materially alter the Developer trajectory and induce repeated-tool progress-guard failures (for example, candidate duration 805.453s and 13 exact duplicates versus baseline 127.143s and 4 exact duplicates). Therefore synthetic provider continuation prompts must not be treated as a valid performance fix. The compatibility finding remains unresolved for the real provider path and must be solved without changing task semantics before using live A/B data as performance evidence.

The benchmark scenario was also corrected so the reference document is optional repeated evidence rather than a mandatory duplicate read. The workload must not intentionally force consecutive duplicate tool calls, because that conflicts with the runtime progress-guard safety boundary. Natural duplicate calls remain observable through telemetry and efficiency analysis.

The latest 10-trial serial / 4-developer live A/B sample contains 8 valid and 2 invalid trials. Baseline success was 0.8000 and candidate success was 1.0000; reliability was preserved and cache effects were observed, but the aggregate verdict remains `no_clear_efficiency_gain`. Valid-trial medians were +1.74% duration, -5.41% LLM calls, -4.08% input tokens, -1 exact-duplicate tool call, -1 duplicate-execution tool call, and 0 median cache-hit change. The two invalid trials independently tripped the progress guard in baseline (`read_file` / `run_command`), so they must not be used as performance evidence. The next optimization conclusion should therefore remain correctness-first rather than claiming a performance win.

### 18.4 Extension Architecture
- [x] Audit Plugin / Tool / Agent / Workflow extension boundaries
- [x] Define stable integration contracts
- [x] Prevent plugin APIs from bypassing security boundaries
- [x] Add extension compatibility tests

#### 18.4 Tool extension slice — completed
- [x] Audit existing PluginHost ↔ ToolRegistry / ToolInvocationService boundary
- [x] Define reserved `tools` extension point
- [x] Introduce host-owned `PluginToolInvocationAdapter`
- [x] Bind a trusted role at adapter construction time
- [x] Prevent raw `ToolRegistry` / raw callable / workspace / `ToolInvocationService` exposure through the `tools` extension
- [x] Preserve canonical capability, permission, argument-validation, audit, and tracing boundaries
- [x] Add focused regression coverage for raw-registry rejection, adapter acceptance, fixed-role behavior, and audit preservation

The first extension slice is implemented around the existing production invocation boundary. The reserved `tools` plugin extension point requires a host-owned `PluginToolInvocationAdapter`; raw internal tool services are rejected.

#### 18.4 Agent extension slice — completed
- [x] Audit existing `AgentRouter` / `BaseAgent` / `AgentResult` boundary
- [x] Define reserved `agents` extension point
- [x] Introduce host-owned `PluginAgentInvocationAdapter`
- [x] Bind a trusted Agent role at adapter construction time
- [x] Preserve existing singleton-role and Developer-pool routing semantics
- [x] Prevent raw `AgentRouter` / `BaseAgent` / LLM / tool-loop state exposure through the `agents` extension
- [x] Isolate mutable `Task` input from plugin-visible Agent execution
- [x] Isolate mutable `AgentResult` output from host runtime state
- [x] Add focused regression coverage for adapter-only registration, fixed-role behavior, task/result isolation, and Developer-pool routing
- [x] Document the Agent extension boundary

The Agent extension slice reuses the production `AgentRouter` and canonical `AgentResult` contracts. Plugins receive only `invoke(task) -> AgentResult`; host runtime objects remain inaccessible through the extension.

#### 18.4 Workflow extension slice — completed
- [x] Audit existing workflow execution / event / task-manager boundary
- [x] Define reserved `workflow` extension point
- [x] Introduce host-owned workflow invocation/read adapter
- [x] Prevent direct mutation of workflow state or event persistence by plugins
- [x] Preserve workflow authorization, lifecycle, event, persistence, and tracing boundaries
- [x] Add focused workflow-extension regression coverage

The Workflow extension slice reuses the production `TaskWorkflow` entry point. Plugins receive only `execute(task_id) -> detached task snapshot`; workflow state transitions, Agent sequencing, evidence gates, persistence checkpoints, and event emission remain host-owned. Raw `TaskWorkflow`, `TaskManager`, `AgentRouter`, event log, and persistence objects are rejected as reserved workflow extensions.

#### 18.4 Cross-extension compatibility suite — completed
- [x] Verify `tools`, `agents`, and `workflow` adapters can coexist in one plugin contract
- [x] Verify each reserved extension independently rejects its raw internal service
- [x] Verify runtime context cannot substitute a host-approved reserved extension
- [x] Verify reserved extension contracts remain identity-bound at initialization

The cross-extension suite establishes that the three reserved extension points are independently type-gated and remain bound to the exact host-provided adapter instances during plugin initialization.

Full 18.4 extension compatibility is now implemented. Final local full-suite verification remains the acceptance gate before marking Phase 18.4 as fully closed.

### 18.5 Production Readiness Gate
- [ ] Full architecture review
- [ ] Full security regression
- [ ] Full observability regression
- [ ] Full persistence/recovery regression
- [ ] Full test-suite verification
- [ ] Update operational documentation
- [ ] Phase 18 acceptance decision

## Phase 18 working rule
Every Phase 18 increment must follow: repository-state review → smallest contract-preserving change → focused tests → full regression → DevPlan update. Do not infer missing runtime modules from filenames alone; consolidate the actual existing implementation first.
