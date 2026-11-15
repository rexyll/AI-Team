# T21.8 Project E2E Capability Boundary Report

## Status

This report describes the deterministic Python CLI and Node.js Web orchestration scenarios implemented for T21.8. The latest additions are committed on `main`, but their full CI run has not yet been independently confirmed. Therefore this report records implementation scope and intended evidence, not a passing acceptance verdict. T21.8 remains in progress.

## What the deterministic scenarios exercise

Both scenarios invoke the real `ProjectOrchestrator.run()`, default `Orchestrator` / `TaskWorkflow`, `DeveloperWorkspaceManager`, delivery phases, and production command adapters.

| Stage | Executed component | Evidence boundary |
|---|---|---|
| Requirement analysis | Real `RequirementAnalystAgent` | Runs with deterministic `MockLLM`; structured sections and REQ/AC identifiers are consumed by the existing quality checker. This is not live model reasoning. |
| Planning | Scripted Planner test double | Supplies a bounded, deterministic one-task graph; it does not measure autonomous planning quality. |
| Development | Scripted Developer test double | Writes the project through the real task-local workspace lease. Successful output is merged through the real workspace manager; it does not measure autonomous code generation. |
| Task test/review | Scripted Tester and Reviewer test doubles | Exercise the production orchestration gate wiring, but do not independently reason over the implementation. |
| Language adapter | Production Python or Node adapter | Actual install/build/test/smoke/package commands execute through `ToolInvocationService` and the host command boundary. Dependencies remain in task-local `.venv` or `node_modules`. |
| Integration/regression | Production pytest staging runner | Runs tests from a fresh copy of the deployable file tree. Static assets such as Node `dist/index.html` are copied; virtual environments, dependency trees, caches, VCS data and symlinks are excluded. |
| Static quality | Enforced Ruff gate | The two E2E scenarios explicitly require Ruff to pass using the project's conservative E9/F63/F7/F82 rule set. |
| QA | Real `QAAgent` | A deterministic MockLLM requests `list_files`, `read_file` and `run_command` through the real read/execute capability boundary. The mock verdict is derived from the returned file-list, file-content and command-exit-code evidence. This verifies tool wiring and failure-sensitive test behavior, not human-quality adversarial analysis. QA has no product-file write capability. |
| Documentation | Real `DocWriterAgent` | Uses MockLLM. The acceptance mapping test double only selects an exact JUnit selector present in the observed test-case list; when no selector was observed it returns an empty mapping. |
| Security and delivery | Existing deterministic security, acceptance, manifest and packaging implementations | E2E assertions require `SEC_PASSED`, passing executable REQ→AT→JUnit evidence, manifest/package existence and package checksum consistency. |

### Scenario-specific executable behavior

**Python CLI** installs the generated package and invokes the installed Windows console entry point `sample-cli --value 21`; the expected output is `42`. The generated project test also checks a valid invocation and an invalid integer input. Independent QA executes the installed module with a negative integer and requires an actual `exit_code=0` result.

**Node.js Web** runs npm install/build/test/smoke/package through the production Node adapter. A Python JUnit test reads `dist/index.html` from the fresh integration staging copy and checks the application marker. Independent QA lists and reads the built HTML and executes `npm test`; its deterministic verdict is `QA_PASSED` only when the expected file content is observed and the command reports exit code zero. Browser rendering and browser automation are not performed.

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
| `deterministic_orchestration` | Real orchestration, workspace, adapters, tool invocation, pytest, QA wiring and packaging with deterministic MockLLM/scripted role doubles | Implemented; latest CI verification pending |
| `live_provider_llm` | Analyst/Planner/Developer/Tester/Reviewer/QA/DocWriter driven by an explicitly configured real provider with host-managed credentials | Not run; requires user-managed provider credentials and explicit opt-in |
| `external_deployment` | Real deployment to a dedicated external environment, with authenticated health/route evidence and separate operator approval | Not run; no external deployment or publication is performed by default CI |

## Explicit limitations

1. Planner, Developer, Tester and Reviewer use scripted test doubles. Analyst and QA use deterministic MockLLM; DocWriter uses a deterministic MockLLM. The scenarios prove production orchestration and tool-boundary wiring, not end-to-end autonomous reasoning or provider quality.
2. No live ProviderLLM credentials are used. Missing credentials are not interpreted as success.
3. The Windows CI E2E job is the target execution environment (Python 3.14 and Node.js 22). The current new commits still require a successful CI run before acceptance.
4. Browser-based UI acceptance is not run. A static HTML artifact check is not a browser test.
5. No Docker image deployment, cloud deployment, traffic switch, zero-downtime replacement or rollback is performed by these scenarios.
6. No GitHub push, PR creation/update, review mutation or merge is performed. SCM live read/write validation remains a separate T21.5 task requiring a test repository and host-issued approvals.
7. Release approval and publication are not requested by these E2E requirements. Package creation does not imply deployment or publication.
8. Human UAT signatures and authenticated evidence attestation are not integrated.

## Completion gate

T21.8 may be marked complete only after both scenarios pass the current full main CI (including regression, security regression, coverage baseline, and Windows Python/Node E2E), both evidence files are actually produced and uploaded, the artifact schema and privacy checks pass, and this report remains aligned with the observed CI evidence. Live ProviderLLM and external deployment may remain explicitly unavailable, but must not be represented as completed or passed.
