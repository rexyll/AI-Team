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

The defined T21.8 deterministic acceptance scope is **complete**, verified by GitHub Actions run [#576](https://github.com/rexyll/AI-Team/actions/runs/43726548817), commit `4879a17`. Regression passed (2,578 passed / 14 skipped), Security regression passed (252 passed / 9 skipped), Coverage baseline passed (2,558 passed / 14 skipped; all module line/branch thresholds met), and Windows Python/Node E2E passed (7 passed). The `project-e2e-evidence` artifact (two JSON bundles, 8,521 bytes, 30-day retention) and `coverage-baseline-python314` artifact (1,921,832 bytes) were uploaded. Both full project scenarios use production `RequirementAnalystAgent`, `PlannerAgent`, `DeveloperAgent`, `TesterAgent`, `ReviewerAgent`, `QAAgent` and `DocWriterAgent` classes. Developer performs real task-local file/command operations; evidence-aware Tester/Reviewer verdicts require actual command/test evidence and both provenance parent links are asserted. The LLM responses remain deterministic MockLLM; this does not complete live-provider reasoning, browser acceptance, external deployment or human UAT.

- **Python CLI orchestration:** `test_python_cli_requirement_runs_through_project_orchestrator_and_delivery` invokes the real `ProjectOrchestrator.run()` and production Analyst/Planner/Developer/Tester/Reviewer/QA/DocWriter Agent classes. The production DeveloperAgent creates the package and pytest source through a temporary bootstrap written with `write_file`, runs `python -m pytest -q tests/test_cli.py` and requires `exit_code=0` / `1 passed`; the bootstrap self-deletes before task merge. The production TesterAgent only returns `TEST_PASSED` when that exact command and result are present in DeveloperResult; the production ReviewerAgent only approves when the Tester decision and same pytest evidence are present. Both provenance links are asserted. The production Python adapter/`ToolInvocationService` still performs independent `.venv` install/build/test/smoke/package, with enforced Ruff, QA, executable acceptance, security, manifest and package creation. The installed `sample-cli --value 21` command must print `42`.
- **Node.js Web orchestration:** `test_node_web_requirement_runs_through_project_orchestrator_and_delivery` follows the production orchestration/lease/adapter/QA/documentation/acceptance path for npm and registers production DeveloperAgent, TesterAgent and ReviewerAgent classes. Developer writes one temporary `bootstrap-project.js` via `write_file`; the allow-listed `node` command creates the package/lock/source/build/test files and deletes itself; Developer then executes `npm run build` and `npm test`. Evidence-aware Tester requires actual `npm test`, `exit_code=0` and TAP `pass 1`; Reviewer requires `TEST_PASSED` plus the same evidence. Their provenance parent links are asserted. The production Node adapter independently repeats complete install/build/test/smoke/package lifecycle. A Python JUnit test reads `dist/index.html` from isolated integration staging and checks its application marker. QA independently lists/reads the built entry and runs `npm test`.
- **QA verdict behavior:** the deterministic QA MockLLM no longer returns an unconditional canned pass. It inspects the actual results of `list_files`, `read_file` and `run_command`, and returns `QA_PASSED` only when the expected file/path evidence is present and the command reports `exit_code=0`. The real QAAgent still executes through its restricted read/execute capability boundary; no product-file write tool is granted.
- **Analyst, Planner and acceptance mapping:** both scenarios register the real `RequirementAnalystAgent` and production `PlannerAgent`, each with deterministic MockLLM responses. The Planner call is exercised through `ProjectOrchestrator.create_plan()` and its production prompt, JSON extraction, plan schema/dependency validation and plan consumption are asserted. This tests the production Planner component but not autonomous model reasoning. The DocWriter acceptance-mapping mock uses the exact observed JUnit selector list; contract tests ensure it returns no mapping when no executed selector is supplied.
- **Focused production Developer/Tester/Reviewer pipeline:** `test_production_developer_tester_reviewer_pipeline_uses_real_execution_evidence` constructs the production Agent classes and TaskWorkflow. Developer performs two `write_file` calls and one real `run_command` pytest execution; the generated test file reports `2 passed`. The evidence-aware Tester MockLLM returns `TEST_PASSED` only when the actual pytest command, `exit_code=0`, `2 passed` and test file identity are visible in its prompt. The evidence-aware Reviewer MockLLM returns `APPROVED` only when the Tester decision and actual execution evidence are visible. The test asserts Tester provenance points to the Developer result, Reviewer provenance points to Tester feedback, and the workflow reaches `completed`. This is a focused TaskWorkflow test that independently covers the role evidence chain; both full ProjectOrchestrator project scenarios now also use the production Developer/Tester/Reviewer Agent classes, with separate project-specific commands and provenance assertions.
- **Integration staging:** `stage_deliverable_copy` now copies safe regular deliverable files, including static assets required by Node tests, while excluding mutable environments, dependency directories, caches, VCS data and symlinks. Dedicated tests cover asset inclusion and exclusions. Both project E2Es require integration and executable acceptance to pass.
- **Static quality:** both project E2Es enable the enforced Ruff gate and assert its result is `passed`.
- **Execution-mode evidence:** both bundles identify `planner`, `developer`, `tester` and `reviewer` as production Agent classes driven by deterministic/evidence-aware MockLLM (`production_planner_agent_mock_llm`, `production_developer_agent_mock_llm`, `production_tester_agent_evidence_aware_mock_llm`, `production_reviewer_agent_evidence_aware_mock_llm`). Analyst, QA and DocWriter retain their declared deterministic execution modes. These are not `live_provider_llm` runs.
- **Evidence Bundle:** `runtime/project_evidence_bundle.py` emits one JSON bundle for each scenario. The JSON Schema is `docs/project_evidence_bundle.schema.json`; tests cover privacy minimization, canonical digest tampering, malformed records, incomplete leases, missing artifacts, invalid inputs and acceptance traceability. QA tool records are metadata-only; raw arguments and outputs are excluded. Windows CI uploads the two files as `project-e2e-evidence` (30-day retention) after the E2E job.

## Evidence boundaries and remaining work

- The deterministic acceptance gate is complete for both full ProjectOrchestrator scenarios: production `RequirementAnalystAgent`, `PlannerAgent`, `DeveloperAgent`, `TesterAgent`, `ReviewerAgent`, `QAAgent` and `DocWriterAgent` classes are invoked with deterministic MockLLM. Developer performs real task-local file/command operations; Tester/Reviewer decisions fail closed if actual command, successful exit code and test summary evidence are absent. Each workflow asserts Developer→Tester and Tester→Reviewer provenance links. The independent focused TaskWorkflow test additionally proves the same role chain on a minimal calculator project (actual pytest: 2 passed). This validates production Agent and evidence-gate wiring, but **does not prove live model autonomous reasoning or provider quality**.
- CI acceptance for the completed deterministic scope is confirmed by run #576 above. Any subsequent source/test/workflow change must be judged by its own latest main Actions run; do not carry the #576 pass forward to later unverified commits.
- Evidence Bundle upload is confirmed in run #576: artifact `project-e2e-evidence` contains the Python CLI and Node.js Web JSON bundles (8,521 bytes); `coverage-baseline-python314` was also uploaded (1,921,832 bytes). The workflow step-level `AI_TEAM_E2E_EVIDENCE_DIR` uses `runner.temp`; it is intentionally not defined in job-level `env`, because that context is unavailable there.
- The evidence bundle's SHA-256 is an integrity checksum, not a signature, authenticated attestation or tamper-proof audit ledger.
- Live ProviderLLM requires explicit user-managed credentials and remains not run. External deployment/publishing remains not run and requires a dedicated environment plus separate approval.
- Browser-based acceptance is not run; inspecting a generated HTML file is not browser rendering. Docker deployment, traffic switching, zero-downtime replacement and deployment rollback are also outside these project E2E scenarios.
- No GitHub push, PR creation/update, review mutation or merge is performed by the tests. SCM live/read-write validation remains separate and blocked on a dedicated test repository and one-use host approvals.

See [`docs/project_e2e_capability_boundary.md`](project_e2e_capability_boundary.md) for the stage-by-stage capability matrix and completion gate.

T21.8 deterministic Python CLI/Node.js Web acceptance is complete under the gate above. No claim of live ProviderLLM validation, external deployment, browser-based acceptance, authenticated evidence attestation, human UAT signatures, or zero-downtime publication is made.
