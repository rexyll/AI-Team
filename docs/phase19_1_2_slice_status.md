# Phase 19.1.2 — Multi-project admission coordination

Status: implemented; local validation pending.

## Implemented

- `MultiProjectScheduler` coordinates multiple isolated `ProjectScheduler` instances.
- Project arbitration is deterministic using `(project_id, task_id)` ordering.
- Each project retains its own `ResourceGovernor`; no shared mutable resource budget is introduced by the coordinator.
- Scheduling decisions remain pure: no Task status or TaskManager mutation occurs.
- Requests carry `ProjectExecutionScope`; mismatched or unknown projects are rejected.
- Cross-project resource isolation and deterministic arbitration have focused regression coverage.

## Architectural boundary

```text
MultiProjectScheduler
    -> ProjectScheduler
        -> DependencyScheduler
        -> ResourceGovernor

Task lifecycle mutation remains owned by TaskManager / TaskWorkflow.
```

The coordinator must not expose TaskManager, TaskWorkflow, AgentRouter, or raw tool execution handles to callers.

## Validation

Run locally:

```powershell
pytest tests/test_project_scheduler.py tests/test_multi_project_scheduler.py -q
pytest -q
```

Only after both pass should this slice be marked complete in DevPlan.
