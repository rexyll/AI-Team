# Changelog

All notable changes to the AI-Team runtime are documented here. Development
follows the node discipline in `DevPlan.md`; every accepted node carries a
commit SHA as evidence.

## Unreleased — TaskPlan P4: team completeness & standard-flow alignment (2026-11-04)

### Added

- **Three governance roles close the standard development team** (`agents/governance.py`,
  `config/model.py`, `runtime/agent_factory.py`): `security` (security engineer),
  `sre` (release/operations engineer) and `release_manager` (release manager).
  All three are pure LLM-level roles with a **zero tool surface**
  (`ROLE_CAPABILITIES` = empty), so a verdict can never modify product files or
  run commands. Each returns a structured verdict and a rationale summary; the
  evidence block is wrapped in the `untrusted_content` fence.
- **Deterministic security audit** (`runtime/security_audit.py`): offline scan of
  the deliverable for private keys, cloud/provider tokens and dangerous
  constructs (`shell=True`, `verify=False`, `pickle.loads`, `yaml.load`,
  `eval`/`exec`), plus advisory dependency-declaration evidence. One high
  finding yields `SEC_FAILED`; report evidence is masked so no raw secret is
  ever written to `docs/security_audit.md`.
- **Deterministic release go/no-go gate** (`runtime/release_gate.py`): a release
  is never started when integration regression failed, QA is `QA_FAILED` or the
  security audit is `SEC_FAILED`. The release manager may add `RELEASE_NO_GO`
  on top but can never waive a deterministic blocker.
- **Deployment-readiness review** (`runtime/deployment_readiness.py`): checks the
  deployment guide (install/start/rollback), the monitoring contract and
  `MONITORING.md`, the handover document set and, after a release, the release
  notes for the released version; verdict is `SRE_READY` / `SRE_DEGRADED` and
  the report ships as `docs/sre_readiness.md`. External cloud deployment/APM
  remains an explicit, documented limitation.
- **Pipeline wiring** (`core/project_orchestrator.py`): security audit runs after
  QA (its evidence reaches the DocWriter context and the test report), the
  release gate runs before the release phase and records
  `project.release_blocked` when blocked, and the SRE readiness review runs
  after the monitoring contract but before the checksummed manifest. Delivery
  payloads gain `security_verdict`, `sre_verdict` and `release_gate_status`.
- Focused suites: `tests/test_team_governance_roles.py` (15 tests) and
  `tests/test_security_release_workflow.py` (19 tests), including
  "deterministic `SEC_FAILED` cannot be waived by the agent" and
  "`RELEASE_NO_GO` blocks an otherwise green delivery".

## Unreleased — TaskPlan T14: incremental revision of persisted projects (2026-11-04)

### Added

- **Deterministic change impact analysis** (`runtime/change_impact.py`): a
  persisted task graph is merged with the re-planned graph by conservative
  matching (plan id, then normalised title, same role). Completed evidence
  (status, result, review/test history, retry state, tool history) is reused
  only when title, description and the id-mapped dependency set are unchanged;
  changed tasks and their transitive downstream are reset to `pending`, unmatched
  tasks count as new work, removed tasks leave the graph and are reported
  explicitly. No LLM call is involved, so the decision is deterministic and
  offline-verifiable.
- **`ProjectOrchestrator.revise_persisted`**: change request → authoritative
  analyst revision → re-plan → incremental task graph → execute only the
  affected tasks → integration regression / QA / documents / packaging gate →
  atomically write the revised snapshot back (checkpointed at every execution
  boundary). Unaffected completed tasks keep their evidence; failures are
  reported honestly and never replaced by assumed success.
- **CLI `--revise-project PATH --change-request PATH`**: revises an existing
  persisted project snapshot in place (the original requirement is passed as
  the positional argument; workspace anchoring matches a normal delivery).
  `--output json` adds a `revision` report (mode, reused/affected/added/
  removed/reset-completed ids, match bases). When no reliable match exists the
  run falls back to a full re-execution and reports `mode: "full"`.
- Focused suite: `tests/test_incremental_revision.py` (19 tests).

## Unreleased — TaskPlan P3: post-delivery monitoring & defect reflow (2026-11-04)

### Added

- **Monitoring contract** (`runtime/monitoring.py`): after a delivery (and
  before the manifest), the deliverable receives `monitoring/health_contract.json`
  and `MONITORING.md`. The contract declares only offline-verifiable probes —
  release anchor (`release_log.json` version/tag/commit), manifest integrity
  (every checksummed file exists and its SHA-256 matches), and the regression
  suite run from an isolated copy — and states honestly that no cloud APM /
  alerting channel is integrated (there is no deployment target environment).
- **Heartbeat** (`python main.py --monitor-check PATH`): runs the probes,
  writes `monitoring/status.json` with `healthy` / `degraded` / `failed` and
  exits non-zero for anything other than healthy, so cron or Task Scheduler can
  use the exit code as the alerting signal. `--output json` is machine-readable.
- **Defect intake & hotfix reflow** (`runtime/defect_reflow.py`): deterministic
  Markdown parsing (`## 缺陷 DEF-001 标题` with required severity/description
  and optional affected version/reproduction), fail-closed validation (duplicate
  ids, unknown fields, invalid severity, affected version not in release
  history), and generation of a validated hotfix plan (one fix + one
  verification task per defect, plus review) and `hotfix_request.md`
  (`CHG-xxx`, reusable through `--change-request`).
- **Standardized repackage flow** (`core/hotfix_runner.py`, CLI
  `--hotfix-project PATH --defect-intake PATH [--hotfix-version V]`): reuses
  the existing pipeline for integration regression, QA, patch release on the
  same git anchor, manifest and repackaging. Outcomes are recorded honestly in
  `docs/defect_report.md` as `FIXED` / `PENDING` / `FAILED`; `--auto-release`
  controls the release confirmation gate.

## Unreleased — TaskPlan P3: project-type gated UI/UX & specialist roles (2026-11-03)

### Added

- **Deterministic project profile** (`runtime/project_type.py`): keyword-only
  classification (web / desktop / mobile / API / data / CLI / library /
  general) over the customer requirement, reinforced by the analyst draft and
  plan text (requirement weighted heavier). Same input always yields the same
  profile; the matched signals are recorded for audit. No LLM call.
- **UI/UX design role** (`agents/ui_ux.py`, role `ui_ux`): tool-less designer
  that produces an implementable specification (view inventory, layout,
  interaction states, design tokens, responsive breakpoints, WCAG 2.1 AA,
  usability acceptance criteria). Enabled only when the profile requires a
  visible interface and the runtime registers the agent; otherwise the plan is
  left untouched (or a model-emitted `ui_ux` task is downgraded to architecture)
  so the graph stays executable.
- **Plan augmentation**: when enabled, a `UX-001` design task is injected
  deterministically (depending on the architecture tasks), and interface-bearing
  developer tasks gain it as a dependency before implementation. The UI/UX
  specification reaches the DocWriter context (`UI/UX 设计规范`) and the
  design document requirements; delivery docs therefore cover interface design.
- **Developer specialist skill matching**: project-type-enabled specialists
  (frontend / backend / data / desktop / mobile / CLI) are matched per
  developer task from task text and recorded in
  `task.context["developer_specialist"]`; the Developer prompt receives the
  corresponding focus block. Unmatched tasks keep the generic Developer prompt
  (no overclaiming).
- **Role plumbing**: `ui_ux` added to supported/model roles, agent factory,
  context access policy (read-only designer projection), task validation and the
  runtime capability policy with **zero tool capabilities** (design work can
  never modify product files or run commands).

## Unreleased — TaskPlan P3: cross-project knowledge base (2026-11-03)

### Added

- **Cross-project knowledge base** (`runtime/knowledge_base.py`): deterministic
  extraction of reusable assets from delivery evidence — pitfalls (acceptance
  gaps/warnings, integration failure or rework, static-gate failures,
  `QA_FAILED`, unpinned or undeclared dependencies), conventions (pinned
  dependency declarations, semver + git tag + release anchors) and patterns
  (the green delivery baseline). Entry identity is a hash of
  (project, kind, title) so re-extraction deduplicates; the store is a single
  atomic JSON file guarded by a process lock, and corrupt files fail closed.
- **Filtered loading**: entries carry tags, roles and timestamps; search filters
  by kind/tag/role/keyword with a bounded limit and a deterministic ordering
  (newest pitfalls first). Rendered assets are injected as fenced untrusted
  context into the analyst prompt (`历史交付经验`) and the DocWriter context
  (`跨项目知识资产`), with explicit rules that history never overrides the
  customer's current requirement.
- **CLI**: `--knowledge-base PATH` enables load + post-delivery extraction,
  `--knowledge-query TEXT` filters assets, `--knowledge-list [PATH]` is a
  read-only store view (text or `--output json`), and
  `--knowledge-extract PATH` backfills from an existing deliverable
  (`release_log.json` / `docs/acceptance_report.md`).
- **Honest failure handling**: a knowledge write failure is recorded in
  `delivery.knowledge` (`status: failed`, error) and emits
  `project.knowledge_failed`; it never invalidates the finished delivery.

## Unreleased — TaskPlan P2: release planning (2026-11-03)

### Added

- **Milestone release plans** (`--requirements-file`): a UTF-8 Markdown plan
  (`## 里程碑 ...` / `### 需求 ...`, optional `[vX.Y.Z]` per requirement) is
  delivered sequentially, one full delivery and release version per
  requirement. A failure stops the batch, records the remaining requirements
  as `skipped`, and still writes the shared plan document
  (`--release-plan-output`, default `release_plan.md`) with status, acceptance
  verdict, version/tag, deliverable root and error per entry.
- **Milestone labels** (`--milestone` for single deliveries; inherited from the
  plan for batch entries): carried into `RELEASE_NOTES.md`, `release_log.json`
  and the shared plan document.
- **Release history view** (`--release-history [PATH]`): read-only aggregation
  of every `release_log.json` under a base directory (bounded depth, hidden and
  runtime-cache directories pruned), available as a Markdown table or JSON;
  a corrupt log fails closed.

## Unreleased — TaskPlan P0 (2026-11-02)

### Added

- **Product-level integration & regression phase**: after all product tasks,
  the deliverable's full test suite runs from a staged fresh copy with
  structured evidence (summary counts, failed test names, output tail);
  failures feed bounded developer-rework rounds (`REWORK-00N`) through the
  canonical TaskWorkflow with fenced failure evidence; a red suite after the
  last round is reported honestly and packaging is skipped
  (`AI_TEAM_INTEGRATION_MAX_ROUNDS`, default 2;
  `AI_TEAM_INTEGRATION_TIMEOUT`, default 300s).
- **Test-report evidence chain**: integration/regression evidence rides into
  the DocWriter context; `test_report.md` now requires 集成联调/全量回归
  sections and states absence of evidence explicitly.
- **Release phase** (`--release`, `--release-version`, `--auto-release`):
  semver version resolution (explicit version wins; otherwise an automatic
  patch bump from `release_log.json`), deterministic `RELEASE_NOTES.md`, a
  confirmation gate (pending unless confirmed; `--auto-release` skips;
  non-interactive sessions never release), a host-owned git anchor (init
  when needed, single release commit, annotated `v<version>` tag through the
  extended `HostGitOperationService`) and a `release_log.json` whose corrupt
  state fails closed. Release artifacts enter the checksummed manifest and
  the deployment package; the release is gated on the integration verdict
  and never invalidates the finished product.

### Changed

- Repository hygiene: removed stale `runtime/task_manager.py.bak` and the
  corrupted legacy `integration/test_real_team.py` demo; `docs/visio/`
  diagram sources are now tracked.

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
