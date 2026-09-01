# Phase 19.1.3 — Project execution admission handoff

Status: implemented; local validation pending.

## Implemented

- `ProjectExecutionHandoff` bridges `MultiProjectScheduler` admission to the existing `TaskWorkflow.execute(task_id)` boundary.
- Admission creates a transient immutable `ProjectExecutionReservation`; it does not mutate `Task`, `TaskManager`, or `ProjectScheduler` state.
- Reservation accounting is maintained only by the handoff and is isolated by project scope, so one project's concurrency reservation cannot consume another project's budget.
- Admission rejection, execution start/completion/failure, and reservation release are emitted through the existing `WorkflowEventLog` boundary.
- Project-scoped admission/execution counters are recorded through the existing `MetricsRegistry`.
- Project execution is represented by an existing provider-independent `Tracer` span; exception paths finish the span as an error and still release the reservation.
- Unknown-project and scope-mismatch validation remains owned by `MultiProjectScheduler`.

## Architectural boundary

```text
ProjectExecutionHandoff
    -> MultiProjectScheduler
        -> ProjectScheduler
            -> DependencyScheduler
            -> ResourceGovernor
    -> TaskWorkflow.execute(task_id)
    -> WorkflowEventLog / MetricsRegistry / Tracer

Task lifecycle mutation remains owned by TaskManager / TaskWorkflow.
```

The handoff intentionally does not expose `TaskManager`, raw tool execution handles, or a second execution runtime.

## Focused regression coverage

`tests/test_project_execution_handoff.py` covers:

- non-mutating admission reservations;
- per-project concurrency isolation;
- canonical TaskWorkflow execution delegation;
- scheduling/execution audit events;
- metrics and tracing integration;
- failure-safe reservation release;
- unknown-project and scope-mismatch rejection.

## Validation

Run locally:

```powershell
pytest tests/test_project_scheduler.py tests/test_multi_project_scheduler.py tests/test_project_execution_handoff.py -q
pytest -q
```

Only after both pass should this slice be marked complete in the Phase 19 tracking documentation.
