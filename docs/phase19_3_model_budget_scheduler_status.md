# Phase 19.3 — Model-budget-aware scheduler integration

Status: implementation complete; local focused and full regression validation is the acceptance gate.

## Implemented

- Added `ModelBudgetProjectScheduler` as a thin adapter around the existing `ProjectScheduler`.
- Project dependency and execution-resource admission remains owned by `ProjectScheduler`.
- Model token/call admission and primary/fallback route selection remain owned by `ModelGovernance`.
- Observed project model usage remains owned by `ModelUsageLedger`.
- Model admission is evaluated only after project admission succeeds.
- Model budget rejection does not mutate task lifecycle, resource usage, or model usage accounting.
- A successful combined decision exposes the governance-selected `ModelRoute` without exposing provider internals.
- Unhealthy primary routes continue to use the existing explicit fallback policy.
- Project budgets remain isolated because the adapter always queries the ledger using its own project scope.

## Architectural boundary

```text
ModelBudgetProjectScheduler
    -> ProjectScheduler.decide(task)
        -> DependencyScheduler
        -> ResourceGovernor
    -> ModelGovernance.decide(project, usage, request)
        -> ModelUsageLedger.usage_for(project)
    -> ModelRoute

Task lifecycle remains owned by TaskManager / TaskWorkflow.
ModelGovernance remains pure policy.
ModelUsageLedger remains observational accounting.
Provider execution remains outside the scheduler.
```

No reservation mutation, provider invocation, distributed queue, or second scheduler was introduced.

## Regression coverage

`tests/test_model_budget_scheduler.py` covers:

- combined project/model admission;
- model-budget rejection after project admission;
- no accounting mutation on rejection;
- fallback route selection;
- project-admission short-circuiting;
- cross-project model-budget isolation.

## Validation

Run locally:

```powershell
pytest tests/test_model_budget_scheduler.py tests/test_project_scheduler.py tests/test_multi_project_scheduler.py -q
pytest tests/test_model_governance.py tests/test_model_usage_attribution.py tests/test_model_cost.py tests/test_model_governed_llm.py -q
pytest -q
```

Only after the focused and full suites pass should this scheduler integration be treated as accepted.
