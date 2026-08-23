# AI-Team Release Readiness Checklist

This checklist is the release gate for the AI-Team runtime. A release may only be cut when every item below is satisfied and its evidence link is green on the release commit. The final end-to-end smoke contract (`tests/test_release_readiness_smoke_contract.py`) verifies the documented pipeline mechanically; the remaining items are process guarantees recorded in `DevPlan.md`.

## 1. Contract test suites

| Area | Evidence |
|---|---|
| Full suite | `pytest -q` green with zero warnings |
| Cross-boundary contracts | `tests/test_workflow_event_end_to_end_contract.py` |
| Failure injection | `tests/test_failure_injection_contract.py` |
| Security | `tests/test_security_contract.py` |
| LLM mock integration | `tests/test_agent_llm_injection.py` |
| Long-running / bounded parallelism | `tests/test_workflow_event_long_running_contract.py` |
| Performance baseline & regression guard | `tests/test_workflow_event_performance_contract.py`, `tests/test_workflow_event_performance_regression_contract.py` |
| Persistence contention & concurrency | `tests/test_workflow_event_persistence_contention_contract.py`, `tests/test_workflow_event_concurrency_contract.py` |
| Scheduler scalability | `tests/test_orchestrator_scalability_contract.py` |
| Failure + concurrency matrix | `tests/test_workflow_event_failure_concurrency_matrix_contract.py` |
| Documentation & examples contracts | `tests/test_documentation_setup_contract.py`, `tests/test_extension_examples_contract.py`, `tests/test_persistence_recovery_example_contract.py` |
| Production configuration | `tests/test_production_configuration_contract.py` |
| Developer LLM injection boundary | `tests/test_developer_llm_injection_contract.py` |
| Release smoke (final gate) | `tests/test_release_readiness_smoke_contract.py`, `tests/test_release_documentation_contract.py` |

## 2. Documented configuration

- [x] Setup guide: `docs/setup.md`
- [x] Production configuration checklist: `docs/production_configuration.md`
- [x] Runnable examples: `examples/README.md` plus `custom_agent.py`, `custom_llm.py`, `custom_tool.py`, `persistence_query.py`, `persistence_recovery.py`
- [x] Declared dependencies: `requirements.txt` pins `openai==3.1.0`, `python-dotenv==1.2.3`
- [x] Environment variables: `AGNES_API_KEY` (required), `AGNES_BASE_URL`, `AGNES_MODEL` documented with import-time behavior warning

## 3. Runtime invariants

- Immutable workflow events with durable atomic publication (`os.replace()`)
- Read-only query / projection / audit boundaries
- Deny-by-default tool permissions; workspace sandbox path containment
- Agent replaceability: every agent honors constructor-injected `BaseLLM`, including the Developer tool-calling loop
- Recovery parity across independent project and event stores

## 4. Known limitations (accepted for this release)

- Python 3.14 required (PEP 649 lazy annotations); earlier interpreters fail at import
- `config/model.py` eagerly constructs the provider client at import time and requires `AGNES_API_KEY`; lazy initialization is deferred to a post-release refactor node
- Network shares are unvalidated for persistence roots (atomic rename requirement)
- Windows-first platform; other platforms are unvalidated

## 5. Sign-off

A release is ready when:

1. `pytest -q` is fully green on the release branch.
2. The release smoke contract passes, proving requirement → orchestration → events → persistence → restart recovery → cross-store query → audit end to end without network access.
3. Every DevPlan phase entry carries an acceptance record with a commit SHA.
4. This checklist is reviewed against the release commit.
