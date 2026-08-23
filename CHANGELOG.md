# Changelog

All notable changes to the AI-Team runtime are documented here. Development
follows the node discipline in `DevPlan.md`; every accepted node carries a
commit SHA as evidence.

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
