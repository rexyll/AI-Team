# Phase 19 — Production Scale / v0.2 Architecture Plan

## Objective

Move AI-Team from a single-project, correctness-first orchestration core toward a production-oriented multi-project execution platform without introducing a second runtime.

Phase 19 must reuse the existing `TaskManager`, `DependencyScheduler`, `ResourceGovernor`, `TaskWorkflow`, canonical tool invocation boundary, persistence/event projection, security policy, and observability stack.

## 19.1 Multi-project scheduling and resource governance — first slice

### Current repository evidence

The repository already contains:

- `DependencyScheduler` for dependency-aware runnable/admissible task selection.
- `ResourceGovernor` / `ResourceLimits` / `ResourceUsage` for immutable resource admission and accounting.
- `TaskManager` as the canonical mutable task-state owner.
- `TaskWorkflow.execute()` as the canonical task workflow entry point.
- Workflow events, persistence, projections, metrics, tracing, and alerts around the existing execution path.

The remaining architectural gap is that these capabilities are not yet consolidated behind a project-level scheduler contract that can safely arbitrate multiple projects and heterogeneous resource budgets.

### Contract goals

- [x] Define an immutable project execution scope identity.
- [x] Define project-level resource limits and effective limits without duplicating `ResourceGovernor` semantics.
- [x] Define admission decisions separately from task lifecycle mutation.
- [x] Make scheduler decisions deterministic for the same task graph, state snapshot, and resource snapshot.
- [x] Prevent one project from consuming another project's resource budget.
- [x] Preserve dependency blocking semantics and task cancellation semantics.
- [x] Preserve canonical `TaskManager` ownership of mutable task lifecycle state.
- [x] Emit auditable scheduling/admission decisions without persisting model prompts or secrets.
- [x] Add concurrency and cross-project isolation regression coverage.
- [x] Integrate project-level scheduling with existing observability metrics and tracing.

The 19.1 execution handoff is implemented through `ProjectExecutionHandoff`. It keeps reservation accounting transient and project-scoped while delegating actual task lifecycle execution to the existing `TaskWorkflow.execute(task_id)` boundary. Focused and full local verification must remain green before the slice is treated as accepted.

### Non-goals for 19.1

- No new Agent runtime.
- No replacement for `DependencyScheduler`.
- No replacement for `ResourceGovernor`.
- No distributed queue or external broker yet.
- No performance claim until multi-run live evidence is valid.

## 19.2 Long-lived execution and recovery

### 19.2.1 Durable project execution checkpoint contract — implementation complete; local validation pending

- [x] Define immutable project execution checkpoint identity and scope.
- [x] Reuse the canonical `WorkflowCheckpoint` for task state rather than duplicating Task serialization.
- [x] Define recoverable (`admitted` / `started`) versus terminal checkpoint states.
- [x] Provide filesystem-backed atomic checkpoint persistence.
- [x] Provide project-scoped recoverable checkpoint enumeration.
- [x] Reject task/project scope mismatches at the checkpoint boundary.
- [x] Integrate checkpoint publication into `ProjectExecutionHandoff` lifecycle transitions.
- [x] Reconstruct active reservations from durable checkpoints on process restart.
- [x] Define authoritative reconciliation before retrying an ambiguous `started` execution.
- [ ] Add crash/restart integration coverage across checkpoint, TaskManager, and TaskWorkflow.

The checkpoint store remains a control-plane durability boundary rather than a second task-state owner. `ProjectExecutionHandoff` mirrors reservation lifecycle transitions to durable checkpoints and can reconstruct recoverable reservations after restart. Recovery returns candidates only; `reconcile()` requires an explicit authoritative durable outcome before a recovered execution is finalized or left eligible for retry.

## 19.3 Cost / model governance

- [ ] Provider/model routing policy.
- [ ] Per-project token/call budgets.
- [ ] Runtime cost attribution.
- [ ] Fallback/degradation policy.
- [ ] Budget-aware scheduling decisions.

## 19.4 Git / CI / PR collaboration

- [ ] Host-owned Git operation boundary.
- [ ] Branch/worktree lifecycle contracts.
- [ ] CI verification as an evidence-bearing workflow stage.
- [ ] PR status ingestion without allowing external status to bypass local gates.

## 19.5 Plugin ecosystem maturity

- [ ] Extension version compatibility policy.
- [ ] Capability negotiation.
- [ ] Plugin lifecycle health and isolation.
- [ ] Extension compatibility matrix.

## 19.6 Production operations

- [ ] Configuration profiles for development/staging/production.
- [ ] Operational SLO definitions.
- [ ] Alert escalation policy.
- [ ] Artifact/log retention policy.
- [ ] Deployment and rollback runbooks.

## Phase 19 working rule

Use the existing canonical runtime boundaries. Prefer a small contract adapter over a parallel subsystem. Every slice follows: repository-state review → contract definition → focused regression → full regression → controlled live validation where applicable → DevPlan update.
