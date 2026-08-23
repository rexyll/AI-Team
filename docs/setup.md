# AI-Team Setup Guide

This guide describes the current canonical setup and runtime entry points for the AI-Team repository.

## 1. Supported development environment

The repository currently targets:

- Windows 11
- Python 3.14 (required; `tools/registry.py` depends on PEP 649 lazy annotation evaluation and fails to import on Python <= 3.13)
- Git
- Docker (optional for development workflows that require it)
- VS Code (optional)

The project is a Python source tree rather than an installed wheel/package. Run commands from the repository root so imports such as `core.*`, `runtime.*`, and `agents.*` resolve correctly.

## 2. Create the virtual environment

From PowerShell at the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell execution policy prevents activation, use the Python executable inside `.venv` directly instead of changing the project runtime contract.

## 3. Install dependencies

The full agent/provider import chain requires two declared third-party dependencies:

```powershell
pip install -r requirements.txt
```

`requirements.txt` pins the versions validated by the local development environment (`openai`, `python-dotenv`). Contract tests themselves stay network-independent through mock injection; `config/model.py` imports both packages and resolves the shared client lazily on first provider use. See `docs/production_configuration.md` for the full configuration checklist.

Verify the interpreter:

```powershell
python --version
python -m pytest --version
```

## 4. Run the project

The CLI entry point is `main.py` and accepts one required project requirement:

```powershell
python main.py "Build a small personal expense tracker"
```

The CLI creates the default agent router through `runtime.agent_factory.create_agent_router()` and executes the requirement through `core.project_orchestrator.ProjectOrchestrator`.

An empty or missing requirement is rejected. Runtime exceptions are reported on stderr and produce a non-zero process exit code.

## 5. Run tests

Run the complete contract suite from the repository root:

```powershell
pytest -q
```

For a focused test file:

```powershell
pytest tests/test_workflow_event_end_to_end_contract.py -q
```

For a focused Phase 8.6 performance/concurrency matrix:

```powershell
pytest tests/test_workflow_event_performance_contract.py tests/test_workflow_event_performance_regression_contract.py tests/test_workflow_event_persistence_contention_contract.py tests/test_workflow_event_concurrency_contract.py tests/test_orchestrator_scalability_contract.py tests/test_workflow_event_failure_concurrency_matrix_contract.py -q
```

The project treats the full `pytest -q` run as the final acceptance gate for each development-plan node.

## 6. Agent configuration

The default router is created with `runtime.agent_factory.create_agent_router()`.

Supported roles are:

- `architect`
- `developer`
- `tester`
- `reviewer`
- `planner`

Each role uses an `AgentConfig` containing:

- `role`
- `model`
- `temperature`
- `max_tokens`
- `enabled`
- `system_prompt`
- `extra`

Example custom configuration:

```python
from runtime.agent_config import AgentConfig
from runtime.agent_factory import create_agent_router

configs = {
    "architect": AgentConfig(role="architect", model="my-model"),
    "developer": AgentConfig(role="developer", model="my-model"),
    "tester": AgentConfig(role="tester", model="my-model"),
    "reviewer": AgentConfig(role="reviewer", model="my-model"),
}

router = create_agent_router(configs)
```

When custom configurations are supplied, `architect`, `developer`, `tester`, and `reviewer` must be present. `planner` may be omitted and then uses its default configuration.

Do not register two agents for the same role. `AgentRouter` rejects duplicate roles and validates role consistency when the agent exposes a `role` attribute.

## 7. LLM provider and mock execution

LLM integration is intentionally behind the agent/LLM abstraction. Production integrations should inject the provider through the existing runtime contracts rather than making network calls directly from workflow orchestration code.

The contract suite includes deterministic mock LLM/agent integration tests. Use those mocks for local tests and regression work so tests remain network-independent and repeatable.

## 8. Tools, permissions, and workspace sandbox

Tool execution is subject to the existing tool contract, permission policy, and workspace sandbox boundaries. A tool must not be treated as an unrestricted shell or filesystem API.

When adding a tool:

1. Define its schema and argument validation.
2. Register it through the existing tool registry contract.
3. Apply the required permission policy.
4. Keep workspace access inside the configured sandbox boundary.
5. Add contract tests for invalid arguments and denied access.

Security behavior is part of the production contract; do not bypass these layers in examples.

## 9. Persistence and recovery

Workflow events are represented by immutable `WorkflowEvent` values and can be kept in a `WorkflowEventLog` with an optional durable persistence sink.

Filesystem persistence uses `WorkflowEventPersistenceAdapter`:

```python
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter
from runtime.workflow_event_log import WorkflowEventLog

adapter = WorkflowEventPersistenceAdapter("./data/events")
log = WorkflowEventLog(persistence_sink=adapter)
```

The persistence adapter provides immutable event identity, idempotent save-if-absent semantics, conflict detection, atomic publication, and cleanup after write failures.

For operational read-only diagnostics, use `WorkflowEventQueryService`:

```python
from runtime.workflow_event_query import WorkflowEventQueryService

query = WorkflowEventQueryService.from_persistence(
    adapter,
    project_id="PROJECT-001",
)

print(query.lifecycle())
print(query.last_event)
```

To validate recovery across independent project and event stores:

```python
query = WorkflowEventQueryService.from_persisted_project(
    project_persistence,
    adapter,
    project_id="PROJECT-001",
)
```

Query and projection are read-only. They must not write to the event store or mutate runtime state.

## 10. Canonical runtime lifecycle

The current canonical workflow lifecycle is event-driven and must not be inferred from older examples. A simple Developer task whose Reviewer approves on the first review can produce:

```text
task_started
developer_completed
tester_skipped
review_started
reviewer_approved
```

Performance contracts count events produced by this real lifecycle rather than adding artificial events.

Retry, revision, approval, persistence, projection, and recovery semantics are covered by the contract tests described in `DevPlan.md`.

## 11. Development workflow

For each DevPlan node:

1. Read the current `DevPlan.md` and repository implementation.
2. Make the smallest change required by the current node.
3. Add or update contract tests where behavior changes.
4. Run the focused tests.
5. Run `pytest -q`.
6. Record the accepted result and commit in `DevPlan.md`.

Do not mix unrelated architectural changes into a documentation or release-readiness node.
