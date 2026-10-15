# Phase 19.2.1 — Durable project execution checkpoint contract

Status: implemented; local validation pending.

## Implemented

- `ProjectExecutionCheckpoint` provides an immutable execution identity bound to a `ProjectExecutionScope`.
- The checkpoint embeds the existing canonical `WorkflowCheckpoint`; Task serialization is not duplicated.
- `admitted` and `started` are explicitly recoverable states; `completed`, `failed`, and `released` are terminal states.
- `ProjectExecutionCheckpointStore` provides filesystem-backed atomic publication and replacement.
- Recoverable checkpoints can be enumerated globally or by project scope.
- Path-like reservation identities are rejected.
- Task/project scope mismatches are rejected before a checkpoint can be persisted.
- `ProjectExecutionHandoff` can durably mirror admission, started, completed, failed, and released transitions.
- `ProjectExecutionHandoff.recover()` reconstructs active project-scoped reservations without executing tasks or mutating TaskManager state.
- `ProjectExecutionHandoff.reconcile()` requires an explicit authoritative outcome before a recovered execution can be finalized or left eligible for retry.

## Architectural boundary

```text
ProjectExecutionCheckpointStore
    -> ProjectExecutionCheckpoint
        -> ProjectExecutionScope
        -> WorkflowCheckpoint
            -> Task snapshot

ProjectExecutionHandoff
    -> transient reservation accounting
    -> durable checkpoint publication/recovery
    -> canonical TaskWorkflow.execute(task_id)

TaskManager / TaskWorkflow remain the authoritative mutable lifecycle owners.
```

The checkpoint store is not a replacement for `TaskStateStore`, `TaskManager`, or `WorkflowEventPersistenceAdapter`. It persists the execution-control-plane identity needed to reconstruct project admission after a process restart. Recovery returns candidates only; reconciliation requires the authoritative durable task/result state to determine whether an ambiguous execution completed, failed, or is safe to retry.

## Validation

Run locally:

```powershell
pytest tests/test_project_execution_checkpoint.py tests/test_project_execution_checkpoint_handoff_integration.py tests/test_project_execution_handoff.py tests/test_project_scheduler.py tests/test_multi_project_scheduler.py -q
pytest -q
```

Only after both pass should 19.2.1 be marked accepted.
