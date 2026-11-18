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

Install the platform-specific Python 3.14 lock. On Windows PowerShell:

```powershell
python -m pip install --disable-pip-version-check "pip==25.3"
python -m pip install --disable-pip-version-check --index-url https://pypi.org/simple --require-hashes -r requirements-windows-py314.lock
```

For the complete development/test toolchain, use `requirements-dev-windows-py314.lock` instead. On Linux, use the corresponding `requirements-linux-py314.lock` or `requirements-dev-linux-py314.lock`. The lock files contain resolved transitive dependencies and SHA-256 hashes; installation fails if a required hash is missing or does not match. These locks target Python 3.14 and their named operating system.

`requirements.txt` and `requirements-dev.txt` remain the reviewed top-level dependency inputs; do not install them directly when reproducibility and hash verification are required. Changes to either input trigger the cross-platform lock-generation workflow, which resolves and verifies candidates before committing the updated locks to `main`.

The MCP bridge is an independent external project and is not installed from this repository. Do not install an undocumented or missing MCP requirements file here. Contract tests themselves stay network-independent through mock injection; `config/model.py` imports both provider packages and resolves the shared client lazily on first provider use. See `docs/production_configuration.md` for the full configuration checklist.

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

When adding an Agent-visible tool:

1. Define its schema and argument validation.
2. Register it through the existing Agent tool registry contract.
3. Apply the required permission policy.
4. Keep workspace access inside the configured sandbox boundary.
5. Add contract tests for invalid arguments and denied access.

The `git_command` primitive is intentionally **host-owned**. It remains part of the complete tool contract for compatibility and schema validation, but it is not exposed through `TOOL_REGISTRY` to Agents. Host Git operations must go through `runtime.host_git.HostGitOperationService`, which validates the authorized workspace, repository root, operation vocabulary, paths, revisions, and commit message before invoking the underlying Git primitive.

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

Retry, revision, approval, persistence, projection, and recovery semantics are covered by the contract tests described in `DevPlan.md`.

## 11. Local MCP bridge service (external)

The local MCP bridge that lets cloud-based LLM hosts access an authorized
local folder is an **independent third-party service** and is no longer part
of this repository. It lives in its own project (`../web_host_bridge` next to
this repository) with its own documentation, tests, and configuration
(`WEB_HOST_BRIDGE_*` environment variables). AI-Team retains no dependency on
it, and the service has no dependency on AI-Team.

The AI-Team production readiness gate no longer includes an MCP section; the
service runs its own test suite and release gate in its own repository.

## 12. Development workflow

For each DevPlan node:

1. Read the current `DevPlan.md` and repository implementation.
2. Make the smallest change required by the current node.
3. Add or update contract tests where behavior changes.
4. Run the focused tests.
5. Run `pytest -q`.
6. Record the accepted result and commit in `DevPlan.md`.

Do not mix unrelated architectural changes into a documentation or release-readiness node.


## 10. Host deployment recovery inventory

The CLI entry point is the current process-level Host lifecycle. Deployment
history is opt-in; no database is created for ordinary users unless the host
sets `AI_TEAM_DEPLOYMENT_HISTORY` or passes `--deployment-history`.

PowerShell:

```powershell
$env:AI_TEAM_DEPLOYMENT_HISTORY = "C:\AI-Team-Host\deployments.sqlite3"
python main.py "Build a small personal expense tracker"
```

Linux/macOS:

```bash
export AI_TEAM_DEPLOYMENT_HISTORY="$HOME/.local/share/ai-team/deployments.sqlite3"
python main.py "Build a small personal expense tracker"
```

When configured, every `main.py` process startup opens the host-owned SQLite
store and performs a read-only inventory of unfinished replacement journals
before dispatching the requested operation. The first configured Host startup
creates the private database schema if the file does not yet exist; subsequent
startup scans open the existing database in SQLite read-only mode. Unfinished
operations are reported to stderr, preserving machine-readable JSON on stdout.
A corrupt configured database fails startup closed. The parent directory is
created with private permissions and the SQLite database is restricted to the
current user on POSIX systems.

To inspect the full inventory without running a project operation:

```powershell
python main.py --deployment-recovery-inventory --output json
# or explicitly select a history store
python main.py --deployment-history C:\AI-Team-Host\deployments.sqlite3 --deployment-recovery-inventory
```

The standalone inventory command requires an existing database and opens it
with SQLite `mode=ro`; it never creates a missing database or modifies
existing deployment state.

This startup hook currently inventories the `docker-local` provider only.
The startup inventory does not run Docker commands. The separate
`--deployment-recovery-inspect` command explicitly inspects recorded
immutable container IDs, but does not change traffic, abort or resume a
replacement, update a journal, or release a scope reservation.
`needs_reconciliation` remains locked. It is a startup detection hook, not an
automatic recovery or safe Docker rollback implementation.

For the combined operator evidence (both immutable runtime inspections and
live Router/HAProxy route read-back), run the standalone command:

```powershell
python main.py --deployment-reconciliation-readback --output json
# or select the Host database explicitly
python main.py --deployment-history C:\\AI-Team-Host\\deployments.sqlite3 --deployment-reconciliation-readback
```

This report reads the existing deployment journal, both immutable Docker
container IDs, the durable Router registry and digest-bound Host state, then
queries the live HAProxy selector and selected backend endpoint/state. It
never creates or adopts a Router scope. Missing registry/state or unavailable
Docker/HAProxy observations are reported as not-found, unsupported,
unavailable, or mismatch; they do not become inferred route success. The
command never changes the selector, active deployment pointer, journal phase,
Host state, container lifecycle, or scope reservation. It performs no retry,
rollback, stop, cleanup, or automatic reconciliation; every report records
`automatic_action: none`.
