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

- Install: editable install from project metadata, otherwise install `requirements.txt`; skipped if no manifest.
- Build: `python -m build` when package metadata exists; otherwise a compile-only check (`python -m compileall -q .`).
- Test: `python -m pytest -q` when pytest-style test files exist; otherwise skipped.
- Package: `python -m build` when package metadata exists; otherwise unsupported.
- Smoke: test suite when present, otherwise compile-only check.
- Deploy: unsupported until a deployment provider is configured.

### Node.js (npm)

Detection signal: a valid `package.json`.

- Install: `npm ci --ignore-scripts --no-audit --no-fund` only when an npm lockfile (`package-lock.json` or `npm-shrinkwrap.json`) exists. pnpm/yarn lockfiles are detected but not executed by this first adapter.
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

CI evidence for the orchestration wiring and audited tool-service tests: [run 43598140624](https://github.com/rexyll/AI-Team/actions/runs/43598140624),
2,273 passed / 9 skipped and 233 security tests passed / 9 skipped. The orchestrator-level test uses a stubbed command implementation behind the real ToolInvocationService; the adapter-level Python and Node fixtures separately execute real commands through ToolInvocationService. A Windows-host run against the production PowerShell-backed terminal remains outstanding.

## Security and execution boundaries

- The adapter receives a project root and reads only known manifest files for detection/planning.
- Command strings are authored by trusted adapter code, not copied from project manifest values. Script names are selected from fixed adapter templates; manifest contents do not become shell command fragments.
- No shell chaining or arbitrary executable is introduced. Commands must pass the existing `run_command` executable allowlist.
- Execution is subject to the caller's role authorization and active task workspace context.
- Node install uses `--ignore-scripts` to avoid executing dependency lifecycle scripts during installation. It may still need network access to fetch packages; the current adapter does not itself configure or broaden network egress.
- Build/package/test outcomes are based on the tool result's explicit `exit_code` marker. Missing or nonzero exit codes fail closed.
- Deployment is explicitly unsupported; a local package artifact is not represented as a production deployment.

## Current maturity and remaining work

The adapter contracts, Python/npm planning rules, timeout schema and invocation-service executor are implemented. GitHub Actions tests verify detection, ambiguity, supported/skipped/unsupported decisions, bounded timeout propagation, invocation through the tool service, fail-closed result parsing, and actual Python plus Node/npm fixture execution across install/build/test/package/smoke. Latest evidence: [run 43595491731](https://github.com/rexyll/AI-Team/actions/runs/43595491731), 2,267 passed / 9 skipped and 233 security tests passed / 9 skipped.

This is not yet a claim of end-to-end Node.js delivery. Remaining T21.3 work:

1. Wire the adapter executor into project-level integration/package orchestration without bypassing existing tool authorization.
2. Run real Python and Node.js fixture projects through install/build/test/package/smoke on a supported host, with network-free fixtures where possible.
3. Add explicit support or deterministic unsupported results for pnpm/yarn, and define how read-only dependency caches can be safely shared with Developer workspaces.
4. Keep deploy unsupported until a deployment provider is implemented and verified.
