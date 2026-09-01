# Phase 19.1 Slice Status

## Implemented

- `runtime/project_scheduler.py` adds the first project-level scheduling contract without introducing a second runtime.
- `ProjectExecutionScope` provides an immutable normalized project identity.
- `ProjectAdmissionDecision` separates admission decisions from mutable task lifecycle state.
- `ProjectScheduler` composes the existing `DependencyScheduler` and `ResourceGovernor`.
- Cross-project task affinity is validated before scheduler construction.
- Admission decisions do not mutate `TaskManager` or `Task` state.

## Focused regression coverage

`tests/test_project_scheduler.py` covers:

- scope identity normalization and immutability;
- dependency-ready admission within the existing resource governor;
- cross-project isolation;
- non-mutating admission decisions;
- concurrency-budget rejection.

## Remaining 19.1 work

- Concurrency and cross-project isolation at the execution integration boundary.
- Scheduling/admission audit emission through the existing workflow/event observability stack.
- Metrics and tracing integration for project-level scheduling decisions.
- Focused plus full regression verification after integration.

## Architectural constraint

This slice intentionally does not replace `DependencyScheduler`, `ResourceGovernor`, `TaskManager`, or `TaskWorkflow`, and it does not introduce a distributed queue/broker.
