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

T21.8 remains **in progress**, and its current deterministic implementation is verified by GitHub Actions run [#565](https://github.com/rexyll/AI-Team/actions/runs/43722145806), commit `f4a3be1`. Regression passed (2,578 passed / 14 skipped), security regression passed (252 passed / 9 skipped), coverage baseline passed (2,558 passed / 14 skipped, all module line/branch thresholds met), and Windows Python/Node E2E passed (7 passed). The `project-e2e-evidence` artifact (two JSON bundles, 7,953 bytes, 30-day retention) and `coverage-baseline-python314` artifact (1,921,850 bytes) were uploaded. The two full project scenarios use production `PlannerAgent` with deterministic MockLLM, while their Developer/Tester/Reviewer remain scripted. A separate focused TaskWorkflow test now exercises the production DeveloperAgent, TesterAgent and ReviewerAgent classes using actual `write_file` and pytest command execution, fail-closed evidence-aware MockLLM decisions, and verified provenance links. This does not complete live-provider reasoning, browser acceptance or external deployment.

- **Python CLI orchestration:** `test_python_cli_requirement_runs_through_project_orchestrator_and_delivery` invokes the real `ProjectOrchestrator.run()`, a real Developer task lease and merge, the production Python adapter/`ToolInvocationService`, a real `RequirementAnalystAgent` using MockLLM, a real `QAAgent` using a result-aware MockLLM and read/execute tools, a `DocWriterAgent` using MockLLM, integration/regression, enforced Ruff, executable acceptance, security, manifest and package creation. It runs the installed `sample-cli --value 21` command and requires output `42`.
- **Node.js Web orchestration:** `test_node_web_requirement_runs_through_project_orchestrator_and_delivery` follows the same production orchestration/lease/adapter/QA/documentation/acceptance path for npm. The Node build creates `dist/index.html`; a Python JUnit test reads that asset from the isolated integration staging copy and checks its application marker. QA independently lists and reads the built entry and runs `npm test`.
- **QA verdict behavior:** the deterministic QA MockLLM no longer returns an unconditional canned pass. It inspects the actual results of `list_files`, `read_file` and `run_command`, and returns `QA_PASSED` only when the expected file/path evidence is present and the command reports `exit_code=0`. The real QAAgent still executes through its restricted read/execute capability boundary; no product-file write tool is granted.
- **Analyst, Planner and acceptance mapping:** both scenarios register the real `RequirementAnalystAgent` and production `PlannerAgent`, each with deterministic MockLLM responses. The Planner call is exercised through `ProjectOrchestrator.create_plan()` and its production prompt, JSON extraction, plan schema/dependency validation and plan consumption are asserted. This tests the production Planner component but not autonomous model reasoning. The DocWriter acceptance-mapping mock uses the exact observed JUnit selector list; contract tests ensure it returns no mapping when no executed selector is supplied.
- **Focused production Developer/Tester/Reviewer pipeline:** `test_production_developer_tester_reviewer_pipeline_uses_real_execution_evidence` constructs the production Agent classes and TaskWorkflow. Developer performs two `write_file` calls and one real `run_command` pytest execution; the generated test file reports `2 passed`. The evidence-aware Tester MockLLM returns `TEST_PASSED` only when the actual pytest command, `exit_code=0`, `2 passed` and test file identity are visible in its prompt. The evidence-aware Reviewer MockLLM returns `APPROVED` only when the Tester decision and actual execution evidence are visible. The test asserts Tester provenance points to the Developer result, Reviewer provenance points to Tester feedback, and the workflow reaches `completed`. This is a focused TaskWorkflow test; it does not mean the two full ProjectOrchestrator project scenarios have replaced their scripted Developer/Tester/Reviewer fixtures.
- **Integration staging:** `stage_deliverable_copy` now copies safe regular deliverable files, including static assets required by Node tests, while excluding mutable environments, dependency directories, caches, VCS data and symlinks. Dedicated tests cover asset inclusion and exclusions. Both project E2Es require integration and executable acceptance to pass.
- **Static quality:** both project E2Es enable the enforced Ruff gate and assert its result is `passed`.
- **Execution-mode evidence:** both bundles now identify `planner` as `production_planner_agent_mock_llm`; Developer/Tester/Reviewer remain `scripted_test_double`. This is a component-level improvement, not a `live_provider_llm` run.
- **Evidence Bundle:** `runtime/project_evidence_bundle.py` emits one JSON bundle for each scenario. The JSON Schema is `docs/project_evidence_bundle.schema.json`; tests cover privacy minimization, canonical digest tampering, malformed records, incomplete leases, missing artifacts, invalid inputs and acceptance traceability. QA tool records are metadata-only; raw arguments and outputs are excluded. Windows CI uploads the two files as `project-e2e-evidence` (30-day retention) after the E2E job.

## Evidence boundaries and remaining work

- In the two full ProjectOrchestrator scenarios, Planner is the production `PlannerAgent` driven by deterministic MockLLM, while Developer/Tester/Reviewer remain scripted role doubles. Separately, the focused TaskWorkflow test invokes production DeveloperAgent, TesterAgent and ReviewerAgent classes: Developer writes two files and actually runs pytest (2 passed); Tester derives its pass from the real command evidence; Reviewer derives approval from the Tester result plus the same execution evidence; both provenance parent links are asserted. Analyst and QA are real agent classes using deterministic MockLLM; DocWriter also uses MockLLM. This validates production component integration and the evidence chain, but **does not prove autonomous model reasoning or live provider quality**.
- CI acceptance for the current deterministic implementation is confirmed by run #565 above. Any subsequent source/test/workflow change must be judged by its own latest main Actions run; do not carry the #565 pass forward to later unverified commits.
- Evidence Bundle upload is confirmed in run #565: artifact `project-e2e-evidence` contains the Python CLI and Node.js Web JSON bundles (7,953 bytes); `coverage-baseline-python314` was also uploaded (1,921,850 bytes). The workflow step-level `AI_TEAM_E2E_EVIDENCE_DIR` uses `runner.temp`; it is intentionally not defined in job-level `env`, because that context is unavailable there.
- The evidence bundle's SHA-256 is an integrity checksum, not a signature, authenticated attestation or tamper-proof audit ledger.
- Live ProviderLLM requires explicit user-managed credentials and remains not run. External deployment/publishing remains not run and requires a dedicated environment plus separate approval.
- Browser-based acceptance is not run; inspecting a generated HTML file is not browser rendering. Docker deployment, traffic switching, zero-downtime replacement and deployment rollback are also outside these project E2E scenarios.
- No GitHub push, PR creation/update, review mutation or merge is performed by the tests. SCM live/read-write validation remains separate and blocked on a dedicated test repository and one-use host approvals.

See [`docs/project_e2e_capability_boundary.md`](project_e2e_capability_boundary.md) for the stage-by-stage capability matrix and completion gate.

No claim of T21.8 completion, live ProviderLLM validation, external deployment, browser-based acceptance, authenticated evidence attestation or zero-downtime publication is made.
