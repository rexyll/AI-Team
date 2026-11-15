# AI Development Team

AI-powered software development team.

## Current status

**Phase 20 — Full-Pipeline Automation Closure** is the current development phase on `main`, tracked in [`TaskPlan.md`](TaskPlan.md). Phases 0–19 completed their planned acceptance work (see [`DevPlan.md`](DevPlan.md)); Phase 20 closes the remaining pipeline stages so a single requirement runs end to end: requirement → analysis → architecture → development → unit tests → **product-level integration & regression (bounded rework)** → packaging → **release (semver, release notes, git anchor)** → **post-delivery monitoring / defect reflow** → **incremental revision of persisted projects**.

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

After a delivery ships, run its deterministic monitoring heartbeat (verifies the
release anchor, manifest checksums and regression suite; exits non-zero when
unhealthy). The deliverable also carries `MONITORING.md` and
`monitoring/health_contract.json`:

```powershell
python main.py --monitor-check F:\workspace\projects\some_delivery
```

To route customer defects back into a released deliverable (validated defect
intake -> hotfix tasks -> integration regression -> patch release -> repackage):

```powershell
python main.py --hotfix-project F:\workspace\projects\some_delivery --defect-intake defects.md --auto-release
```

The defect file uses `## 缺陷 DEF-001 标题` sections with `严重级别` and
`描述` (plus optional `影响版本` / `复现步骤`); the outcome is written to
`docs/defect_report.md` and the same defects are also expressed as
`hotfix_request.md` (`CHG-xxx`) for the regular change-request path.

A persisted project snapshot can receive the same change-request channel
incrementally: unaffected completed tasks keep their evidence and only the
tasks affected by the revision (plus their downstream) are executed again.

```powershell
python main.py "<original requirement>" --revise-project F:\workspace\projects\snapshots\PROJECT-001.json --change-request change.md
```

The report (`--output json` exposes it under `revision`) lists reused,
affected, added and removed task ids; when the revised plan cannot be matched
reliably the run honestly falls back to a full re-execution (`mode: "full"`).

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

Twelve specialized agents form a closed development loop:

- Analyst Agent — normalizes requirements of any clarity into a structured draft spec (REQ ids, acceptance criteria, explicit assumptions, open questions)
- Planner Agent — requirement decomposition and task graph
- Architect Agent — structure and interface design
- Developer Agent — implementation, test authoring, and fixes; skills are matched per task from the project profile (frontend / backend / data / desktop / mobile / CLI focus blocks)
- Tester Agent — test-evidence review with TEST_PASSED / TEST_FAILED verdicts
- Reviewer Agent — final approval gate (APPROVED / REVISION_REQUIRED)
- QA Agent — product-level adversarial verification after integration; `QA_FAILED` blocks release but never packaging
- UI/UX Designer Agent — information architecture, layout, interaction states, design tokens and accessibility; enabled only when the detected project profile requires a visible interface (web / desktop / mobile or explicit interface signals)
- Security Engineer Agent — triages the deterministic security audit (secret leakage, dangerous constructs, dependency declarations); `SEC_FAILED` always wins and blocks release
- SRE Agent — reviews deployment readiness (deployment guide, monitoring contract and runbook, handover documents, release notes); external cloud deployment/APM remains an explicit limitation
- Release Manager Agent — release go/no-go over recorded integration, QA, security and acceptance evidence; deterministic blockers cannot be waived
- Doc Writer Agent — standard delivery document set (requirements / design / test report / deployment guide / user manual) plus a checksummed delivery manifest

The three governance agents are tool-free by policy: their verdict can never modify product files or run commands.

The project-level pipeline closes the loop: Analyst → **deterministic project profile (project type + UI/UX + developer specialties)** → Planner → optional UI/UX design task before interface work → Developer pool with per-task Tester/Reviewer gates → **product-level integration & regression suite (bounded rework rounds; a red suite is reported honestly and never packaged)** → **product-level adversarial QA** → **deterministic security audit** → DocWriter document set → deterministic acceptance → **release go/no-go gate (deterministic blockers + release-manager verdict)** → **release phase (version, notes, git anchor, release log)** → **post-delivery monitoring contract** → **deployment-readiness review (SRE)** → checksummed manifest → deployment package with smoke verification.

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
## License

This project is licensed under the [PolyForm Small Business License 1.0.0](LICENSE). It permits use, modification, and redistribution subject to its terms. Commercial use for the benefit of a company is permitted only when the company satisfies the license's small-business thresholds (fewer than 100 employees and independent contractors, and revenue below the CPI-adjusted USD 1,000,000 threshold stated in the license). Other commercial use requires separate permission from the licensor. The standard PolyForm Small Business text does not separately grant the broad personal/non-commercial permission found in PolyForm Noncommercial; personal use outside the stated permitted purposes therefore requires separate permission. Third-party dependencies retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
