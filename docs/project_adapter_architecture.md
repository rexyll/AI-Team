# Project Adapter Architecture

## Purpose

`runtime/project_adapters.py` separates language/toolchain detection from the existing product-category classifier in `runtime/project_type.py`. A project may be categorized as a web app, API, CLI, desktop app or library while its executable toolchain is independently identified as Python or Node.js. Multiple detected toolchains are reported as ambiguous and require an explicit adapter selection; the registry never guesses.

## Contract

- `ProjectAdapter.detect(root)` returns a deterministic detection record or `None`.
- `ProjectAdapter.plan(root, action)` returns a structured plan for `install`, `build`, `test`, `package`, `smoke` or `deploy`.
- Plan status is one of `supported`, `skipped` or `unsupported`. Absence of tests/scripts is a skip; missing reproducibility prerequisites or an unconfigured deployment provider is unsupported.
- A `ProjectCommand` contains one command, a workspace-relative working directory and a bounded timeout.
- Adapters only describe commands. They never call subprocess, a shell, or a tool implementation directly.
- `ProjectAdapterExecutor` sends every command through `ToolInvocationService.invoke(tool_name="run_command")`. The normal role capability policy, workspace sandbox, command allowlist and tool execution audit remain authoritative.
- The run_command schema now exposes a bounded timeout (1–3600 seconds).

## Initial adapters

### Python

Detection signals: `pyproject.toml`, `requirements.txt`, `setup.py`, `setup.cfg`, or top-level Python source.

- Install: create a lease-local `.venv` with `--system-site-packages`, then install project/requirements into it; optionally install `requirements-dev.txt`. pip cache is scoped to `.ai-team-cache/pip`; skipped if no dependency manifest.
- Build: use the lease-local interpreter for `python -m build --no-isolation` when package metadata exists; otherwise a compile-only check (`python -m compileall -q .`).
- Test: use the lease-local interpreter for `python -m pytest -q` when pytest-style test files exist; otherwise skipped.
- Package: use the lease-local interpreter for `python -m build --no-isolation` when package metadata exists; otherwise unsupported.
- Smoke: test suite through the lease-local interpreter when present, otherwise compile-only check.
- Deploy: unsupported until a deployment provider is configured.

### Node.js (npm)

Detection signal: a valid `package.json`.

- Install: `npm ci --ignore-scripts --no-audit --no-fund --cache .ai-team-cache/npm` only when an npm lockfile (`package-lock.json` or `npm-shrinkwrap.json`) exists. `node_modules` and npm cache remain lease-local. pnpm/yarn lockfiles are detected but not executed by this first adapter.
- Build: `npm run build` only when the script exists.
- Test: `npm test --if-present` only when the test script exists.
- Package: `npm pack --ignore-scripts --json`.
- Smoke: test script when present; otherwise skipped.
- Deploy: unsupported until a deployment provider is configured.

## Project orchestration integration

`ProjectOrchestrator` now includes an opt-in adapter phase in the existing
integration gate. Enable it with `AI_TEAM_PROJECT_ADAPTERS=1`; if a project
contains more than one supported toolchain, select one explicitly with
`AI_TEAM_PROJECT_ADAPTER=python` or `AI_TEAM_PROJECT_ADAPTER=node`.

The phase plans and executes install, build, test, smoke and package in that
order. It uses a fresh `ToolInvocationService` and invokes only the registered
`run_command` tool as the developer role. A task-local `workspace_scope`
anchors every command to the deliverable root. Existing capability checks,
argument schema validation, command allowlist, timeout enforcement and tool
execution history remain in force. A failed command or ambiguous toolchain
fails the integration gate and is included in bounded rework evidence;
skipped/unsupported individual actions are retained as explicit evidence.

The phase is disabled by default. Dependency installation can contact package
registries and modify dependency directories; enabling it is an explicit
operator decision. The legacy integration suite and static gate continue to
run independently, including on a fresh staged copy.

Developer task leases have a separate opt-in setup switch: `AI_TEAM_TASK_ENVIRONMENTS=1`.
It provisions only the install action before the Developer workflow, inside the
task's private lease. Python `.venv`, Node `node_modules` and pip/npm caches under
`.ai-team-cache` are lease-local, discarded with that lease, and never merged
into the canonical source tree. Shared cache reuse is intentionally deferred.
The adapter selection variable `AI_TEAM_PROJECT_ADAPTER` is shared by both
flows.

CI evidence: [run 43599217740](https://github.com/rexyll/AI-Team/actions/runs/43599217740) passed both jobs. Linux regression: 2,280 passed / 10 skipped; security regression: 233 passed / 9 skipped. The Windows production-terminal smoke passed (1 passed), exercising lease-local venv install, build/test/smoke/package and a deliberately failing test to verify non-zero exit propagation. The orchestrator-level tests use a stub command behind the real ToolInvocationService; adapter-level Python and Node fixtures execute real commands through ToolInvocationService with a subprocess-backed test registry.

## Security and execution boundaries

- The adapter receives a project root and reads only known manifest files for detection/planning.
- Command strings are authored by trusted adapter code, not copied from project manifest values. Script names are selected from fixed adapter templates; manifest contents do not become shell command fragments.
- No shell chaining or arbitrary executable is introduced. Commands must pass the existing `run_command` executable allowlist.
- Execution is subject to the caller's role authorization and active task workspace context.
- Node install uses `--ignore-scripts` to avoid executing dependency lifecycle scripts during installation. It may still need network access to fetch packages; the current adapter does not itself configure or broaden network egress.
- Build/package/test outcomes are based on the tool result's explicit `exit_code` marker. Missing or nonzero exit codes fail closed.
- Deployment is explicitly unsupported; a local package artifact is not represented as a production deployment.

## Current maturity and remaining work

The first Project Adapter milestone (T21.3 v1) is complete. Verified capabilities include Python and Node/npm detection/planning, explicit unsupported states, bounded command execution through ToolInvocationService, opt-in ProjectOrchestrator integration, workspace scoping, failure evidence/rework, and real fixture execution for install/build/test/package/smoke. CI verifies both the audited invocation boundary and the production Windows terminal.

Known boundaries are explicit rather than silently inferred:

1. Node support is npm-only. pnpm/yarn lockfiles are detected, but install is unsupported until dedicated lockfile-aware adapters are implemented.
2. Dependency caches are not shared between Developer workspaces. This remains coupled to the T21.2 workspace/dependency-environment design.
3. Adapter integration is disabled by default because install can access package registries; enable it deliberately with `AI_TEAM_PROJECT_ADAPTERS=1`.
4. Deploy remains unsupported until a deployment provider is implemented and verified.
