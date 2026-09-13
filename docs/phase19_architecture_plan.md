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

### 19.2.1 Durable project execution checkpoint contract — implementation complete

- [x] Define immutable project execution checkpoint identity and scope.
- [x] Reuse the canonical `WorkflowCheckpoint` for task state rather than duplicating Task serialization.
- [x] Define recoverable (`admitted` / `started`) versus terminal checkpoint states.
- [x] Provide filesystem-backed atomic checkpoint persistence.
- [x] Provide project-scoped recoverable checkpoint enumeration.
- [x] Reject task/project scope mismatches at the checkpoint boundary.
- [x] Integrate checkpoint publication into `ProjectExecutionHandoff` lifecycle transitions.
- [x] Reconstruct active reservations from durable checkpoints on process restart.
- [x] Define authoritative reconciliation before retrying an ambiguous `started` execution.
- [x] Add crash/restart integration coverage across checkpoint, TaskManager, and TaskWorkflow.

The checkpoint store remains a control-plane durability boundary rather than a second task-state owner. `ProjectExecutionHandoff` mirrors reservation lifecycle transitions to durable checkpoints and can reconstruct recoverable reservations after restart. Recovery returns candidates only; `reconcile()` requires an explicit authoritative durable outcome before a recovered execution is finalized or left eligible for retry.

## 19.3 Cost / model governance — first slice

- [x] Define immutable provider/model route contract.
- [x] Define per-project token/call budget contract.
- [x] Define deterministic model admission decisions without mutating usage state.
- [x] Define explicit primary-route health and fallback selection semantics.
- [x] Add cross-project budget-isolation and fallback regression coverage.
- [x] Attribute actual runtime token/call usage to projects.
- [x] Integrate governance admission with the canonical LLM invocation boundary.
- [x] Add provider/model cost-rate configuration.
- [x] Add budget-aware scheduler integration.
- [x] Add bounded degradation and fallback observability.

The first 19.3 slice is intentionally policy-only: `ModelGovernance` does not execute LLM calls and does not become a second runtime owner. Runtime usage attribution (`ProviderLLM` → `ModelUsageLedger`), the governed invocation boundary (`ModelGovernedLLM`), cost-rate configuration (`ModelCostRateRegistry` / `ProjectCostProjection`), budget-aware scheduling (`ModelBudgetProjectScheduler`), and bounded fallback/rejection telemetry are implemented and covered by the focused suites listed in `phase19_3_governed_llm_status.md` and `phase19_3_model_budget_scheduler_status.md` plus the full regression.

## 19.4 Git / CI / PR collaboration

- [x] Host-owned Git operation boundary.
- [ ] Branch/worktree lifecycle contracts.
- [ ] CI verification as an evidence-bearing workflow stage.
- [ ] PR status ingestion without allowing external status to bypass local gates.

The Git boundary slice is implemented through `runtime.host_git.HostGitOperationService` with semantic operations only; raw `git_command` is host-only and not agent/plugin-visible. See `phase19_4_git_ci_pr_collaboration_status.md`.

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
