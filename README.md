# AI Development Team

AI-powered software development team.

## Current status

**Phase 20 — Full-Pipeline Automation Closure** is the current development phase on `main`, tracked in [`TaskPlan.md`](TaskPlan.md). Phases 0–19 completed their planned acceptance work (see [`DevPlan.md`](DevPlan.md)); Phase 20 closes the remaining pipeline stages so a single requirement runs end to end: requirement → analysis → architecture → development → unit tests → **product-level integration & regression (bounded rework)** → packaging → **release (semver, release notes, git anchor)**.

The current development branch is:

`main`

The Phase 18 production-readiness gate is:

```powershell
python tools/run_production_readiness.py
```

See [`DevPlan.md`](DevPlan.md) for the complete implementation and acceptance history.

## Quick start

The current supported development environment is Windows 11 + Python 3.14. Create and activate a virtual environment from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Run the test suite:

```powershell
pytest -q
```

Run the production-readiness gate:

```powershell
python tools/run_production_readiness.py
```

Run the CLI with a project requirement:

```powershell
python main.py "Build a small personal expense tracker"
```

For machine-readable automation output:

```powershell
python main.py "Build a small personal expense tracker" --output json
```

To run the release phase after a successful delivery (semver version,
release notes, deliverable git anchor, release log; the confirmation prompt
is skipped with `--auto-release`):

```powershell
python main.py "Build a small personal expense tracker" --release --auto-release
```

To deliver a milestone plan (multiple requirements, sequential deliveries, one
version per delivery, and a shared `release_plan.md` outcome document):

```powershell
python main.py --requirements-file requirements_plan.md --release --auto-release
```

To inspect the merged version history across every deliverable:

```powershell
python main.py --release-history
```

To reuse lessons from earlier deliveries (historical patterns, pitfalls and
conventions load into requirement analysis and delivery documentation; new
lessons are extracted into the store after each delivery):

```powershell
python main.py "Build a small personal expense tracker" --knowledge-base knowledge
python main.py --knowledge-list knowledge
python main.py --knowledge-extract F:\workspace\projects\some_delivery --knowledge-base knowledge
```

For the complete setup, configuration, persistence/recovery, security boundaries, and canonical workflow lifecycle guide, see [`docs/setup.md`](docs/setup.md).

For the CLI contract, see [`docs/cli_reference.md`](docs/cli_reference.md).

For configuration rules, see [`docs/configuration_reference.md`](docs/configuration_reference.md) and [`docs/production_configuration.md`](docs/production_configuration.md).

For plugin extensions, see [`docs/plugin_api.md`](docs/plugin_api.md).

For operational readiness criteria, see [`docs/production_readiness.md`](docs/production_readiness.md).

For operational diagnosis, see [`docs/operational_troubleshooting.md`](docs/operational_troubleshooting.md).

Reference examples are under `examples/` and are deterministic, provider-independent, and covered by regression tests.

## Architecture

Nine specialized agents form a closed development loop:

- Analyst Agent — normalizes requirements of any clarity into a structured draft spec (REQ ids, acceptance criteria, explicit assumptions, open questions)
- Planner Agent — requirement decomposition and task graph
- Architect Agent — structure and interface design
- Developer Agent — implementation, test authoring, and fixes; skills are matched per task from the project profile (frontend / backend / data / desktop / mobile / CLI focus blocks)
- Tester Agent — test-evidence review with TEST_PASSED / TEST_FAILED verdicts
- Reviewer Agent — final approval gate (APPROVED / REVISION_REQUIRED)
- QA Agent — product-level adversarial verification after integration; `QA_FAILED` blocks release but never packaging
- UI/UX Designer Agent — information architecture, layout, interaction states, design tokens and accessibility; enabled only when the detected project profile requires a visible interface (web / desktop / mobile or explicit interface signals)
- Doc Writer Agent — standard delivery document set (requirements / design / test report / deployment guide / user manual) plus a checksummed delivery manifest

The project-level pipeline closes the loop: Analyst → **deterministic project profile (project type + UI/UX + developer specialties)** → Planner → optional UI/UX design task before interface work → Developer pool with per-task Tester/Reviewer gates → **product-level integration & regression suite (bounded rework rounds; a red suite is reported honestly and never packaged)** → **product-level adversarial QA** → DocWriter document set → deterministic acceptance → **release phase (version, notes, git anchor, release log)** → checksummed manifest → deployment package with smoke verification.

The current runtime separates Agent routing, task orchestration, workflow lifecycle, durable workflow-event persistence, read-only projection, and operational query boundaries.

## Runtime contracts

Important production contracts include:

- `AgentRouter` for role-based Agent registration and routing.
- `AgentConfig` / `create_agent_router()` for Agent configuration.
- `WorkflowEventLog` for immutable in-memory workflow events.
- `WorkflowEventPersistenceAdapter` for filesystem-backed durable events.
- `WorkflowEventQueryService` for read-only operational diagnostics.
- `PluginHost` for versioned, capability-scoped plugin lifecycle management.
- Host-owned plugin adapters for `tools`, `agents`, and `workflow` extension points.

A simple Developer task with first-review approval follows the canonical event lifecycle:

```text
task_started
developer_completed
tester_skipped
review_started
reviewer_approved
```

Performance tests count the events generated by this real lifecycle rather than adding artificial events.

## Development Environment

- Windows 11
- Python 3.14
- Git
- Docker
- VS Code

## Project Structure

- `agents/`: Agent implementations
- `core/`: project/workflow orchestration and canonical domain behavior
- `runtime/`: task execution, configuration, persistence, event log, projection, query, scheduling, and extension boundaries
- `security/`: permission and sandbox security boundaries
- `integration/`: integration-facing components
- `tests/`: contract and regression test suite
- `docs/`: developer and runtime documentation
- `examples/`: deterministic reference projects for supported runtime contracts
- `projects/`: projects developed by the AI team

## Development process

Each DevPlan node follows:

1. Plan against the current repository state.
2. Implement the smallest required change.
3. Run focused contract tests.
4. Run `pytest -q` as the acceptance gate.
5. Record the accepted result and commit in `DevPlan.md`.

See [`docs/setup.md`](docs/setup.md) for the detailed setup and runtime guide.