# T21.8 Real Project E2E Acceptance

## Purpose

Validate that AI-Team can take a natural-language requirement through the existing production orchestration path and produce a runnable, tested, documented deliverable for two representative project types:

1. Python CLI/API.
2. Node.js Web application.

This is an acceptance exercise for the integrated runtime, not a replacement implementation and not a benchmark of a particular LLM vendor.

## Current evidence and gaps

The repository already has the following building blocks:

- runtime/project_adapters.py detects Python and npm projects and describes install/build/test/package/smoke commands.
- ProjectAdapterExecutor routes commands through ToolInvocationService, preserving role permissions, workspace scoping, command allowlists, timeouts and audit history.
- runtime/project_environment.py provisions Python .venv or Node node_modules inside a task lease.
- ProjectOrchestrator can opt into the adapter phase with AI_TEAM_PROJECT_ADAPTERS=1.
- tests/test_project_adapter_windows_e2e.py executes a real Python adapter workflow on Windows CI.
- tests/test_project_environment.py covers Python and Node lease-local environment behavior, including install failure.
- tests/test_project_adapter_orchestration.py covers orchestrator wiring with a stub command executor.

These tests do not yet prove a complete natural-language-to-deliverable run for both project types. In particular, the current Node coverage is primarily adapter/environment contract coverage, and the existing Windows production smoke is Python-focused.

## Acceptance scenarios

### A. Python CLI/API project

Use a bounded, deterministic requirement for a small Python CLI or HTTP API with:

- an explicit entry point and documented invocation;
- a small, testable domain behavior;
- automated tests that exercise success and invalid-input behavior;
- dependency declarations and reproducible setup instructions;
- a README with scope, commands, and limitations.

The run must use the canonical Analyst → Planner/Architect → Developer → Tester/Reviewer → integration/regression → QA/security → documentation/acceptance → packaging/release pipeline. Validate the generated artifact by invoking its documented CLI/API behavior, not only by inspecting files.

### B. Node.js Web project

Use a bounded npm project with:

- a valid package.json and committed package-lock.json;
- a deterministic build script;
- a test script that exits non-zero on failure;
- a minimal web entry point and documented local start/smoke procedure;
- no implicit deployment or cloud provisioning.

The run must explicitly select the Node adapter if the workspace also contains Python metadata. npm ci must use the lockfile and --ignore-scripts; build/test/package/smoke commands must pass through the normal run_command ToolInvocationService boundary. Validate the built artifact and a local smoke behavior. Do not claim browser-based acceptance unless a browser runner is actually present and executed.

## Required evidence per scenario

Record a machine-readable evidence bundle with:

- input requirement and normalized requirement/spec identifiers;
- project type and selected adapter, including detection signals;
- task graph and terminal task states;
- workspace/lease identifiers and proof that mutable dependencies remained lease-local;
- tool execution audit records (role, tool, command identity, exit code, duration; never secrets);
- install/build/test/package/smoke outcomes and explicit skipped/unsupported reasons;
- executable acceptance results tied to requirement/acceptance IDs;
- QA, security, integration/regression and release gate verdicts;
- delivery manifest and artifact checksums;
- release notes/version/git anchor when release is explicitly approved;
- limitations and any human approval required.

A successful run requires all mandatory actions to pass. A skipped action may be accepted only when the scenario explicitly marks it optional and the reason is retained. Unsupported deployment must remain unsupported; packaging is not deployment.

## Execution modes and honesty rules

Separate three kinds of evidence:

1. Deterministic orchestration E2E: use MockLLM or scripted test doubles while exercising real production orchestration, workspace, tool invocation, adapters and executable project commands. This is repeatable CI evidence, but does not prove provider quality.
2. Live ProviderLLM E2E: use an explicitly configured provider and user-managed credentials in a manually triggered/opt-in run. Never store credentials in the repository, artifacts, task context or logs. Missing credentials must report unavailable/not_run, not pass.
3. External service/deployment E2E: only when a dedicated test account/environment and explicit approval exist. Do not deploy, publish, create external resources or perform remote writes as part of default CI.

No test may replace the production command boundary with a stub and then describe the resulting run as a real executable project E2E. Stub-based tests remain useful for orchestration contract coverage, but must be labeled accordingly.

## Failure and security matrix

At minimum verify:

- ambiguous Python + Node toolchain detection fails closed unless the adapter is explicitly selected;
- missing npm lockfile does not run npm install as a fallback;
- non-zero install/build/test/package/smoke exit codes fail the adapter/integration gate;
- timeout, denied command, workspace escape and symlink/path escape are rejected;
- task-local .venv, node_modules and caches are not merged into the canonical source tree or delivery archive;
- secrets are absent from evidence, reports and logs;
- no deployment or SCM write occurs without its separate explicit approval path;
- missing provider credentials are reported honestly.

## Completion criteria

T21.8 is complete only after:

- both project scenarios have deterministic end-to-end evidence through the canonical runtime;
- real project commands execute through the production ToolInvocationService boundary;
- executable acceptance is performed against the produced deliverables;
- all mandatory tests and the full repository CI pass;
- the evidence bundles and a capability-boundary report are committed under docs/ or the repository's established test-artifact convention;
- any live ProviderLLM or external deployment validation that cannot be performed is explicitly listed as a remaining limitation, not silently counted as complete.

## Current status (2026-11-15)

Partial execution evidence exists; T21.8 is **not complete**. The Python CLI orchestrator test is implemented, but its CI result is not yet recorded.

- Python CLI: Windows production adapter E2E installs/builds/tests/smokes/packages a real package, executes the installed console script, checks success and invalid input, and verifies a deliberate failing test.
- Node.js Web adapter: Windows production adapter E2E runs npm install/build/test/smoke/package and checks the built artifact and command audit.
- Node.js Web orchestration: `test_node_web_requirement_runs_through_project_orchestrator_and_delivery` invokes the real `ProjectOrchestrator.run()` and default production `Orchestrator`/`TaskWorkflow`, executes Developer → Tester → Reviewer gates, writes the project inside a `DeveloperWorkspaceManager` task lease, merges only after task success, then runs the production Node adapter through `ToolInvocationService`, generates documentation with `DocWriterAgent` + `MockLLM`, runs deterministic security/dependency/monitoring/SRE evidence, writes the delivery manifest and creates a package. The test verifies lease merge records and produced artifacts. It runs on Windows CI with Node.js 22.
- A Windows-specific lease merge defect was found by this test: `_fsync_file` opened staged/backup files read-only before `os.fsync`, causing `EBADF` on Windows. It now opens `rb+`; full regression, security regression, coverage baseline and Windows production E2E all pass in CI run [#43714970246](https://github.com/rexyll/AI-Team/actions/runs/43714970246).

Evidence boundaries and remaining work:

- The planner, developer, tester and reviewer in the orchestration E2E are deterministic scripted role doubles. Only the document writer is driven by `MockLLM`; this does **not** prove full MockLLM-driven agent reasoning or provider quality.
- Python CLI `ProjectOrchestrator` coverage has now been added in `tests/test_project_adapter_node_e2e.py` as `test_python_cli_requirement_runs_through_project_orchestrator_and_delivery` (commit `3b204e7`). It runs on the Windows toolchain job and exercises the real orchestrator, task lease, Python adapter/`ToolInvocationService`, document writer + `MockLLM`, package/manifest generation, and the installed `sample-cli --value 21` command (`42` expected). The commit's CI result has not yet been verified in this record, so this is implementation evidence, not accepted CI evidence.
- The full Analyst → Planner → Developer → Tester/Reviewer → integration → QA/security → documentation/acceptance → package chain is not yet covered by one end-to-end scenario. Analyst and QA agent stages are not part of the current Node test.
- A committed, machine-readable evidence bundle tying requirement IDs, task graph, lease IDs/merge results, command audit, acceptance, checksums and release gates together is still required.
- Live ProviderLLM requires explicit user-managed credentials and remains not run. External deployment/publishing remains not run and requires a dedicated environment plus separate approval.

No claim of T21.8 completion, live ProviderLLM validation, external deployment, browser-based acceptance, or zero-downtime publication is made.
