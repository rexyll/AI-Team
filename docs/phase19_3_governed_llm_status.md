# Phase 19.3 — Governed LLM invocation boundary

Status: implemented; local validation pending.

## Implemented

- `ModelGovernedLLM` provides a thin `BaseLLM` policy adapter at the LLM invocation boundary.
- Project usage is read from the canonical `ModelUsageLedger` before admission.
- `generate()` estimates input/output request usage and performs a pure `ModelGovernance.decide()` before provider execution.
- `generate_with_tools()` applies the same admission path to tool-calling turns.
- Primary-route health can be supplied as a stable boolean or evaluated through a health callback for each invocation.
- Governance-selected fallback routes are resolved to explicitly configured `BaseLLM` instances.
- A governance-selected but unconfigured route fails closed before provider execution.
- Admission rejection raises `ModelAdmissionError` carrying the immutable `ModelAdmissionDecision`.
- Provider execution and actual usage attribution remain owned by the wrapped LLM; the governance adapter does not double-record usage.

## Architectural boundary

```text
ModelGovernedLLM
    -> ModelGovernance.decide()
    -> ModelUsageLedger.usage_for(project)
    -> selected BaseLLM route
        -> provider execution
        -> actual usage attribution (when configured)

ModelGovernance remains pure policy.
ModelUsageLedger remains observational accounting.
BaseLLM / ProviderLLM remain the execution boundary.
```

This slice intentionally does not add reservation mutation or a second LLM runtime. Budget admission is fail-closed before provider execution, while actual provider usage remains authoritative telemetry.

## Focused regression coverage

`tests/test_model_governed_llm.py` covers:

- primary-route admission;
- pre-invocation call-budget rejection;
- fallback selection;
- fail-closed missing route configuration;
- per-invocation health callback evaluation;
- tool-call admission;
- route mapping validation.

## Validation

Run locally:

```powershell
pytest tests/test_model_governance.py tests/test_model_usage_attribution.py tests/test_model_cost.py tests/test_model_governed_llm.py -q
pytest -q
```

Only after both pass should this slice be marked accepted in `DevPlan.md`.
