# Changelog

All notable changes to the AI-Team runtime are documented here. Development
follows the node discipline in `DevPlan.md`; every accepted node carries a
commit SHA as evidence.

## v0.9.1 (2026-09-06)

Reliability and observability increments after the Phase 18 acceptance,
driven by live single- and multi-developer end-to-end runs.

### Added

- Delivery capability upgrade: a **Requirement Analyst** role normalizes
  requirements of any clarity (complete feature list down to a single
  sentence) into a structured draft specification with REQ-numbered
  requirements, acceptance criteria, explicitly labeled assumptions and open
  questions; a **Delivery Documentation Writer** role produces the standard
  document set (requirements / design / test report / deployment guide /
  user manual) into `<deliverable>/docs/`; a deterministic checksummed
  delivery manifest (`DELIVERY_MANIFEST.md`) closes the delivery phase.
  Both roles are project-level orchestration steps - core workflow semantics
  are unchanged - and the delivery phase is non-fatal by design.
- **Deterministic acceptance verification** (`runtime/acceptance.py`): a
  requirement traceability matrix (REQ-xxx against requirements / design /
  test-report artifacts) judges product-requirement conformance separately
  from code-quality review. 必须-level requirements must be traceable and
  carry acceptance criteria; the verdict and gap list are written to
  `<deliverable>/docs/acceptance_report.md` and emitted as
  `project.acceptance_completed`.
- **Customer clarification protocol**: `main.py --clarifications <file>`
  feeds authoritative customer answers to the analyst's open questions back
  into the requirement analysis.
- **Interactive clarification session** (`runtime/clarification_session.py`):
  a resumable session state machine (awaiting_answers → clarified →
  delivered) with an I/O-injectable terminal prompt loop and JSON
  persistence; `main.py --interactive` analyzes, prompts, saves, and
  continues into delivery, `--resume-session` finishes a paused session.
- **Deployment bundle** (`runtime/deployment.py`): the delivery package now
  includes `install.ps1` / `install.sh` bootstrap installers, a Dockerfile
  template, and a deterministic smoke verification that runs the
  deliverable's test suite from a fresh copy — live-verified with smoke
  PASSED and a 14-member deployment bundle.
- **Deterministic delivery packaging** (`runtime/packaging.py`): the delivery
  phase bundles the product, documents and manifest into a single
  reproducible zip (sorted members, per-member SHA-256 verification, junk
  excluded) and fails closed if the archive does not match the manifest.
- **Analyst self-correction & analyze-only mode**: the draft spec is
  deterministically quality-checked at authoring time (sections present,
  must-level acceptance criteria) with one corrective retry, and
  `main.py --analyze-only` produces the draft + clarification worksheet
  without starting a full delivery. The traceability parser merges
  requirement blocks across sections (list rows + AC tables under a
  验收标准 section) based on live drafts.
- **Live-delivery hardening**: analyst-draft hallucinated directories can no
  longer become enforced constraints (draft rides via task context as an
  explicitly advisory section; extraction sees only the original text);
  terminal denials carry remediation hints; the tester judges the LATEST
  execution of repeated evidence commands; the progress guard is
  workspace-revision-aware (post-fix re-verification is not a duplicate).

- Workflow events now carry a monotonic per-project `sequence` assigned by
  `WorkflowEventLog` at append time, persisted through the JSON sink, and
  restored across restarts; `list_for_project` / `list_for_task` order by the
  causal sequence when present while legacy unsequenced events keep the
  timestamp contract (`tests/test_workflow_event_sequence.py`).
- Provider tool-continuation protocol guard (`ProviderLLM._repair_tool_continuation`):
  incomplete `assistant(tool_calls)` turns are repaired before the wire by
  trimming only unanswered declarations and orphaned responses - no synthetic
  content - so a broken turn can no longer kill the whole task. Live
  multi-developer runs confirmed 17 successful repairs in one project.
- GitHub Actions CI (`.github/workflows/ci.yml`): full pytest regression plus
  the security regression suite on Python 3.13/3.14.
- Property-based dependency-graph tests with seeded random DAGs
  (`tests/test_dependency_graph_property.py`).
- Provider route circuit breaker (`runtime/llm/circuit_breaker.py`): closed →
  open (consecutive-failure threshold) → half-open probe (cooldown) per route,
  with per-route isolation, bounded event history, and a detached snapshot.
  `ModelGovernedLLM` accepts it as an optional policy layer that evaluates
  primary-route health and records selected-route outcomes, feeding the
  existing fallback selection; default runtime behavior is unchanged without it.
- SQLite workflow event store (`runtime/workflow_event_sqlite_store.py`): an
  optional backend implementing the exact filesystem-adapter contract with WAL
  durability, scalar-column indexes, `BEGIN IMMEDIATE` atomicity, and
  transactional conflict/rollback semantics identical to the JSON writer.
- 10,000-task dependency-graph scalability contract (chain, layered, and
  scheduler readiness timing bounds).
- Windows Job Object process containment (`security/process_sandbox.py`):
  every `run_command` process tree runs inside a Job Object with
  host-configured memory/process ceilings and kill-on-close. A timeout now
  terminates the whole tree instead of orphaning grandchildren; builtin
  `TimeoutError` classifies as `TOOL_TIMEOUT` instead of a generic failure.
- Artifact Store (`runtime/artifact_store.py`): content-addressed,
  checksum-verified large-output storage. Developer tool outputs at or above
  a threshold (default 16 KiB, `AI_TEAM_ARTIFACT_MIN_CHARS`) are archived and
  the execution history keeps a traceable reference, bounding snapshot
  growth; classification, evidence, and model-visible messages are unchanged.
- Tester prompt hardening: the tester has no tools - it must not imitate
  input fence markers or emit tool-call syntax, and its decision marker is
  always the literal first line. The Developer system prompt documents the
  shell-metacharacter and `python -c` prohibitions.
- Gate-retry execution-id collision fix: resumed Developer attempts
  disambiguate reused model call ids (`call_x#2`) instead of crashing -
  both at the agent record layer and inside `ToolInvocationService`.
- Folded-prefix sandbox normalization: `WorkspaceSandbox.resolve` strips the
  mandated directory's parent-segment chain from relative paths, so
  deliverables land flat in the mandated directory even when the model
  re-prepends the literal prefix; escape protection is unaffected.
- Guard-trip retry round: the gate intercepts a progress-guard trip before
  the failure outcome is applied, records the reason as retry feedback, and
  re-runs the developer in the next round (terminal only when rounds run
  out).

### Fixed

- `ContextCompactingLLM._apply_recent_window` no longer cuts the conversation
  between an `assistant(tool_calls)` message and the tool messages answering
  it; the orphaned tool result violated the OpenAI continuation protocol and
  was the real root cause of the upstream `No user query found in messages`
  rejection recorded in DevPlan 18.3.
- Terminal policy denials now surface the model-facing reason through
  `TerminalPolicyError` (allow-list, shell-metacharacter and blocked-argument
  rejections keep their safe, bounded message; sandbox containment stays
  sanitized).
- Developer safe-batch preflight kept the failure reason instead of reducing
  failed reads to bare `None` in the tool message.
- `set_default_workspace_root` creates the anchored sandbox root eagerly; a
  mandated root that no tool run had created yet made every workspace-relative
  read fail before the agents could produce anything.

### Verified

- Full regression: 2023 passed; security regression suite: pass.
- Live single-developer runs on a real provider with process containment and
  artifact archiving active: delivered CLI tools executed directly with all
  unit tests passing (reviewer-revision retry rounds exercised the
  duplicate-id fix end to end).
- Live runs on a rate-limited provider exercised the guard-trip retry round
  and confirmed flat deliverable placement under the folded-prefix
  normalization.
- Single-developer live run (deepseek): 7/7 tasks completed; delivered
  `greet.py` CLI, 2 unit tests and README accepted by direct execution.
- Multi-developer live run (3 developers): 10/10 tasks completed with
  three-way parallel developer execution; delivered toolkit (strutils,
  mathutils, main.py demo, 25 unit tests, README) accepted by direct
  execution.

## v0.9.0-rc (2026-08-23)

First release candidate of the AI-Team runtime: a sustainable, recoverable,
auditable, and verifiable AI software development team operating as a closed
loop of Planner / Architect / Developer / Tester / Reviewer / Orchestrator.

### Added

- Agent foundation with constructor-injected `BaseLLM` across all five roles;
  deterministic `MockLLM` (including scripted tool-calling turns) keeps the
  entire contract suite network-free.
- Task/Workflow lifecycle with dependency-aware scheduling, bounded parallel
  execution, retry/resume, and unified `AgentResult` contracts.
- Tool contract layer: registry, schema validation, deny-by-default
  permission policy, workspace sandbox path containment.
- Immutable workflow events with durable atomic persistence, read-only
  projection/query/audit boundaries, project snapshot persistence and
  cross-store recovery parity.
- Production hardening: failure injection, security contracts, long-running
  workflows, performance baseline and regression guards, concurrency and
  failure/concurrency matrices, scheduler scalability at 512 tasks.
- Runnable examples: custom agent / LLM / tool, persistence + query,
  persistence + recovery walkthrough; each backed by contract tests.
- Documentation set: `docs/setup.md`, `docs/production_configuration.md`,
  `docs/release_readiness.md`, `examples/README.md`.
- Release smoke contract: real agents (mock-injected) driven end to end from
  requirement through orchestration, durable events, restart recovery,
  cross-store query, and tool-execution auditing.

### Fixed

- DeveloperAgent routed provider calls around the injected LLM boundary;
  the tool loop now honors constructor injection via the neutral
  `generate_with_tools()` contract.
- PlannerAgent resolved plans through the module-level `ask_ai` entry point;
  plan creation now flows through the injected LLM.
- ProjectOrchestrator attached the workflow event log without rebuilding the
  workflow event sink, silently dropping all workflow-level lifecycle events
  from durable persistence on the main CLI path.

### Changed

- Provider client construction is lazy: importing the agent chain is
  side-effect free, `AGNES_API_KEY` is validated only on first actual use.
- Third-party dependencies (`openai==3.1.0`, `python-dotenv==1.2.3`) are now
  declared and pinned in `requirements.txt`.

### Known limitations

See `docs/release_readiness.md` §4: Python 3.14 required, Windows-first
platform validation, local filesystems required for atomic persistence roots.
