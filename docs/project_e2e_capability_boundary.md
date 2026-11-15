# T21.8 Project E2E Capability Boundary Report

## Status

The deterministic Python CLI and Node.js Web ProjectOrchestrator acceptance defined for T21.8 is **complete**. GitHub Actions run [#576](https://github.com/rexyll/AI-Team/actions/runs/43726548817), commit `4879a17`, confirms the current `main`: Regression (2,578 passed / 14 skipped), Security regression (252 passed / 9 skipped), Coverage baseline (2,558 passed / 14 skipped; all module line/branch thresholds met), and Windows Python/Node E2E (7 passed). Both `project-e2e-evidence` (8,521 bytes) and `coverage-baseline-python314` (1,921,832 bytes) artifacts were uploaded. Both complete scenarios use production Analyst/Planner/Developer/Tester/Reviewer/QA/DocWriter Agent classes with deterministic/evidence-aware MockLLM; actual tool execution, command results, provenance, integration, QA, security, executable acceptance and packaging are asserted. Live ProviderLLM reasoning, browser acceptance, external deployment, signed UAT and authenticated attestation remain explicitly unverified and are not part of this deterministic completion claim.

## What the deterministic scenarios exercise

Both scenarios invoke the real `ProjectOrchestrator.run()`, default `Orchestrator` / `TaskWorkflow`, `DeveloperWorkspaceManager`, delivery phases, and production command adapters.

| Stage | Executed component | Evidence boundary |
|---|---|---|
| Requirement analysis | Real `RequirementAnalystAgent` | Runs with deterministic `MockLLM`; structured sections and REQ/AC identifiers are consumed by the existing quality checker. This is not live model reasoning. |
| Planning | Production `PlannerAgent` with deterministic `MockLLM` | Exercises the production planning prompt, model call boundary, JSON extraction/schema/dependency validation and ProjectOrchestrator plan consumption. The response is deterministic; this does not measure live autonomous planning quality. |
| Python CLI ProjectOrchestrator development | Production `DeveloperAgent` with deterministic `MockLLM` | Uses `ToolInvocationService` to write one temporary Python bootstrap, executes it to create `pyproject.toml`, the CLI package, pytest file and README, then self-deletes; executes `python -m pytest -q tests/test_cli.py` and requires `exit_code=0` with `1 passed`. The real Python adapter independently installs, builds, tests, smoke-runs and packages the final project. This verifies the production Developer tool loop, not live autonomous code generation. |
| Node.js Web ProjectOrchestrator development | Production `DeveloperAgent` with deterministic `MockLLM` | Uses `ToolInvocationService` to write one temporary bootstrap file, executes `node bootstrap-project.js` to create the package/source/build/test files and self-delete, then executes `npm run build` and `npm test`. The test verifies exactly one successful write, the three ordered command records, exit-code-zero evidence and a passing Node test. This exercises the production Developer tool loop, not live autonomous code generation. |
| ProjectOrchestrator task test/review | Production `TesterAgent` and `ReviewerAgent` with evidence-aware deterministic `MockLLM` in both full project scenarios | Python Tester passes only when the actual `python -m pytest -q tests/test_cli.py` command, `exit_code=0` and `1 passed` are present in DeveloperResult; Node Tester requires `npm test`, `exit_code=0` and TAP `pass 1`. Each Reviewer requires `TEST_PASSED` plus the same execution evidence. Both scenarios assert Tester→Developer and Reviewer→Tester provenance parent links. The model decisions remain deterministic, not a quality benchmark. |
| Focused TaskWorkflow role pipeline | Production `DeveloperAgent`, `TesterAgent` and `ReviewerAgent` with deterministic, evidence-aware `MockLLM` | Developer uses production `write_file` and `run_command` via `ToolInvocationService`; pytest runs for real; Tester only passes when the actual exit code and test summary are present; Reviewer only approves when Tester plus the same execution evidence are present. Developer→Tester→Reviewer provenance links are asserted. This is a focused one-task workflow test, not a full ProjectOrchestrator project build or live model reasoning. |
| Language adapter | Production Python or Node adapter | Actual install/build/test/smoke/package commands execute through `ToolInvocationService` and the host command boundary. Dependencies remain in task-local `.venv` or `node_modules`. |
| Integration/regression | Production pytest staging runner | Runs tests from a fresh copy of the deployable file tree. Static assets such as Node `dist/index.html` are copied; virtual environments, dependency trees, caches, VCS data and symlinks are excluded, and a symlinked delivery root is rejected before path resolution. |
| Static quality | Enforced Ruff gate | The two E2E scenarios explicitly require Ruff to pass using the project's conservative E9/F63/F7/F82 rule set. |
| QA | Real `QAAgent` | A deterministic MockLLM requests `list_files`, `read_file` and `run_command` through the real read/execute capability boundary. The mock verdict is derived from the returned file-list, file-content and command-exit-code evidence. This verifies tool wiring and failure-sensitive test behavior, not human-quality adversarial analysis. QA has no product-file write capability. |
| Documentation | Real `DocWriterAgent` | Uses MockLLM. The acceptance mapping test double only selects an exact JUnit selector present in the observed test-case list; when no selector was observed it returns an empty mapping. |
| Security and delivery | Existing deterministic security, acceptance, manifest and packaging implementations | E2E assertions require `SEC_PASSED`, passing executable REQ→AT→JUnit evidence, manifest/package existence and package checksum consistency. |

### Scenario-specific executable behavior

**Python CLI** installs the generated package and invokes the installed Windows console entry point `sample-cli --value 21`; the expected output is `42`. The generated project test also checks a valid invocation and an invalid integer input. Independent QA executes the installed module with a negative integer and requires an actual `exit_code=0` result.

**Node.js Web** uses the production `DeveloperAgent` with deterministic MockLLM in the full ProjectOrchestrator flow. Developer writes one `bootstrap-project.js` through `write_file`; the allow-listed `node bootstrap-project.js` command creates `package.json`, lockfile, HTML source, build script, Node test and Python JUnit test, then deletes the bootstrap file. Developer next executes `npm run build` and `npm test`; the test asserts the ordered ToolExecutionHistory contains exactly these three completed commands, one successful write, `exit_code=0` evidence and the Node TAP `pass 1` result. The subsequent production Node adapter still independently performs npm install/build/test/smoke/package. A Python JUnit test reads `dist/index.html` from the fresh integration staging copy and checks the application marker. Independent QA lists and reads the built HTML and executes `npm test`; its deterministic verdict is `QA_PASSED` only when the expected file content is observed and the command reports exit code zero. Browser rendering and browser automation are not performed.

**Focused production role pipeline** is covered by `test_production_developer_tester_reviewer_pipeline_uses_real_execution_evidence` on Windows. The production DeveloperAgent writes a calculator module and its pytest tests using `write_file`, then executes `python -m pytest -q tests/test_calculator.py` through the normal PowerShell/ToolInvocationService boundary. The command returns `exit_code=0` and `2 passed`. The production TesterAgent receives this actual DeveloperResult and its evidence-aware MockLLM passes only when the execution evidence is present. The production ReviewerAgent receives the Tester feedback and approves only when both the `TEST_PASSED` decision and the same execution evidence are present. The test asserts both provenance parent links and the final completed TaskWorkflow state. This focused test is independent of the scripted Developer/Tester/Reviewer used by the two full ProjectOrchestrator project scenarios.

## Evidence Bundle

Each orchestration scenario writes a privacy-minimized JSON file using `runtime/project_evidence_bundle.py`. The schema is `docs/project_evidence_bundle.schema.json`; contract tests are in `tests/test_project_evidence_bundle.py`.

The bundle captures:

- a SHA-256 fingerprint and character count for the original requirement, plus parsed REQ identifiers and priority/acceptance metadata;
- project profile and task graph, task terminal states, Tester/Reviewer outcomes, workspace lease ID and merge/discard disposition;
- tool invocation identity, role, tool, status, timestamps, duration and a digest of arguments;
- Analyst, integration, static, QA, security, executable acceptance, release-gate, SRE, monitoring, dependency-scan and SCM-observation summaries;
- exact observed JUnit selector/status mappings, delivery manifest member digests, package digest/checksum comparison and available sidecar digests;
- role execution mode and explicit limitations.

Raw requirement text, analysis/Prompt content, raw command arguments, command output, secret values and local absolute paths are excluded. QA tool audit records are reduced to metadata and an arguments digest before they enter the project delivery object or bundle.

The canonical SHA-256 detects accidental or uncoordinated content modification. It is **not** a digital signature, trusted timestamp, authenticated identity, tamper-proof ledger or provenance attestation. The CI workflow is configured to upload the two JSON files as the `project-e2e-evidence` artifact with 30-day retention; that artifact is not considered available until the corresponding Windows CI run succeeds.

## Execution evidence levels

| Level | Meaning | Current status |
|---|---|---|
| `deterministic_orchestration` | Both full Python/Node ProjectOrchestrator scenarios use production Analyst/Planner/Developer/Tester/Reviewer/QA/DocWriter Agent classes, production workspace/tool/adapter/integration/acceptance/security/packaging boundaries, and deterministic/evidence-aware MockLLM responses; a separate focused TaskWorkflow scenario adds independent Developer→Tester→Reviewer provenance coverage | **Complete for the defined deterministic scope**, verified by full main CI #575 and documentation re-verification #576; not live-provider or autonomous-reasoning evidence |
| `live_provider_llm` | Analyst/Planner/Developer/Tester/Reviewer/QA/DocWriter driven by an explicitly configured real provider with host-managed credentials | Not run; requires user-managed provider credentials and explicit opt-in |
| `external_deployment` | Real deployment to a dedicated external environment, with authenticated health/route evidence and separate operator approval | Not run; no external deployment or publication is performed by default CI |

## Explicit limitations

1. Both full ProjectOrchestrator scenarios invoke production `RequirementAnalystAgent`, `PlannerAgent`, `DeveloperAgent`, `TesterAgent`, `ReviewerAgent`, `QAAgent` and `DocWriterAgent` classes. All model responses are deterministic MockLLM responses; Tester/Reviewer mocks are evidence-aware and fail closed when the real command/result evidence is missing. Their provenance links are validated. This proves production component, tool-boundary and evidence-gate wiring, not live autonomous reasoning or provider quality.
2. No live ProviderLLM credentials are used. Missing credentials are not interpreted as success.
3. The Windows CI E2E job is the target execution environment (Python 3.14 and Node.js 22). The completed deterministic implementation is verified by CI #575 and documentation re-verification #576; subsequent source/test/workflow changes still require their own latest main CI result.
4. Browser-based UI acceptance is not run. A static HTML artifact check is not a browser test.
5. No Docker image deployment, cloud deployment, traffic switch, zero-downtime replacement or rollback is performed by these scenarios.
6. No GitHub push, PR creation/update, review mutation or merge is performed. SCM live read/write validation remains a separate T21.5 task requiring a test repository and host-issued approvals.
7. Release approval and publication are not requested by these E2E requirements. Package creation does not imply deployment or publication.
8. Human UAT signatures and authenticated evidence attestation are not integrated.

## Completion gate

<badge>Completed — deterministic acceptance scope</badge>

The defined T21.8 deterministic acceptance gate is satisfied on `main`:

- Both Python CLI and Node.js Web ProjectOrchestrator scenarios passed the full main CI, including Regression, Security regression, Coverage baseline and Windows Python/Node E2E (run [#576](https://github.com/rexyll/AI-Team/actions/runs/43726548817)).
- Each scenario produced its own Evidence Bundle JSON; both were successfully uploaded as `project-e2e-evidence` (8,521 bytes). The coverage artifact `coverage-baseline-python314` (1,921,832 bytes) was also uploaded.
- Evidence Bundle schema, canonical digest, privacy minimization, acceptance traceability, and failure/invalid-record contracts run in the passing regression suite.
- This report and the acceptance record were updated to match the observed role execution modes and CI evidence.

This completion applies only to deterministic MockLLM orchestration. Live ProviderLLM reasoning, browser rendering/automation, external deployment or publishing, human UAT signatures, SCM live write/merge, and authenticated evidence attestation remain **not run / not verified**. No pass or completion claim is made for those capabilities.
