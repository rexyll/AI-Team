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

## Architectural boundary

```text
ProjectExecutionCheckpointStore
    -> ProjectExecutionCheckpoint
        -> ProjectExecutionScope
        -> WorkflowCheckpoint
            -> Task snapshot

TaskManager / TaskWorkflow remain the authoritative mutable lifecycle owners.
```

The store is deliberately not a replacement for `TaskStateStore`, `TaskManager`, or `WorkflowEventPersistenceAdapter`. Its purpose is to persist the execution-control-plane identity needed to reconstruct project admission after a process restart.

## Next integration boundary

The next increment must connect checkpoint publication to `ProjectExecutionHandoff` without making checkpoint persistence authoritative over TaskManager state. On restart, a recoverable checkpoint is only a recovery candidate; an ambiguous `started` execution must be reconciled with the authoritative durable task/result sink before retry or commit is selected.

## Validation

Run locally:

```powershell
pytest tests/test_project_execution_checkpoint.py tests/test_project_execution_handoff.py tests/test_project_scheduler.py tests/test_multi_project_scheduler.py -q
pytest -q
```

Only after both pass should 19.2.1 be marked complete.
