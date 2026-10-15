# Phase 19.3 — Governed LLM invocation boundary

Status: implementation complete; local focused and full regression validation is the acceptance gate.

## Implemented

- `ModelGovernedLLM` provides a thin `BaseLLM` policy adapter at the LLM invocation boundary.
- Project usage is read from the canonical `ModelUsageLedger` before admission.
- `generate()` estimates input/output request usage and performs a pure `ModelGovernance.decide()` before provider execution.
- `generate_with_tools()` applies the same admission path to tool-calling turns.
- Primary-route health can be supplied as a stable boolean or evaluated through a health callback for each invocation.
- Governance-selected fallback routes are resolved to explicitly configured `BaseLLM` instances.
- A governance-selected but unconfigured route fails closed before provider execution.
- Admission rejection raises `ModelAdmissionError` carrying the immutable `ModelAdmissionDecision`.
- `ProviderLLM` owns authoritative provider-response usage attribution to the canonical `ModelUsageLedger` when configured with a project scope.
- `ModelCostRate` / `ModelCostRateRegistry` provide immutable provider/model pricing and `ProjectCostProjection` derives observational project cost from route-attributed usage.
- `ModelGovernedLLM` optionally emits bounded, provider-independent fallback-selection and admission-rejection counters through `MetricsRegistry` without project-id labels.

## Architectural boundary

```text
ModelGovernedLLM
    -> ModelGovernance.decide()
    -> ModelUsageLedger.usage_for(project)
    -> selected BaseLLM route
        -> provider execution
        -> authoritative usage attribution (ProviderLLM when configured)

ModelGovernance remains pure policy.
ModelUsageLedger remains observational accounting.
ModelCostRateRegistry / ProjectCostProjection remain observational cost accounting.
MetricsRegistry remains provider-independent operational telemetry.
BaseLLM / ProviderLLM remain the execution boundary.
```

This slice does not add reservation mutation or a second LLM runtime. Budget admission is fail-closed before provider execution. Actual usage and cost are derived from provider responses, while fallback and rejection events are observable through low-cardinality metrics.

## Focused regression coverage

`tests/test_model_governed_llm.py` covers:

- primary-route admission;
- pre-invocation call-budget rejection;
- bounded output admission estimates;
- fallback selection;
- fail-closed missing route configuration;
- per-invocation health callback evaluation;
- tool-call admission;
- route mapping validation;
- fallback-selection telemetry;
- admission-rejection telemetry.

The existing model governance, usage attribution, and cost regression suites remain authoritative for their respective contracts.

## Validation

Run locally:

```powershell
pytest tests/test_model_governance.py tests/test_model_usage_attribution.py tests/test_model_cost.py tests/test_model_governed_llm.py -q
pytest -q
```

Only after both pass should this slice be marked accepted in `DevPlan.md`.
