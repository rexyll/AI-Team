from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4
from datetime import datetime, timezone

from core.orchestrator import Orchestrator
from core.project_result import ProjectResult
from runtime.acceptance import (
    acceptance_verdict,
    build_traceability_matrix,
    parse_requirement_entries,
    write_acceptance_report,
)
from runtime.dependency_scan import scan_deliverable_dependencies
from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from agents.analyst import run_quality_checked_analysis
from agents.qa import parse_qa_verdict
from runtime.delivery_manifest import write_delivery_manifest
from runtime.deployment import create_deployment_bundle
from runtime.integration_verification import (
    DEFAULT_INTEGRATION_TIMEOUT,
    DEFAULT_STATIC_TIMEOUT,
    run_integration_suite,
    run_static_quality_gate,
)
from runtime.host_git import HostGitOperationService
from runtime.release import ReleaseRequest, perform_release
from runtime.plan_builder import PlanBuilder
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_validator import validate_plan
from runtime.tool_execution_audit import ToolExecutionAudit
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter
from security.prompt_injection import untrusted_content
from security.workspace import WorkspaceSandbox, resolve_workspace_path


class ProjectOrchestrator:
    """Project-level orchestration entry point."""

    PLANNER_TASK_ID = "PLAN-001"
    ANALYST_TASK_ID = "REQ-ANALYSIS"
    DELIVERY_TASK_ID = "DELIVERY-001"
    QA_TASK_ID = "QA-001"

    def __init__(
        self,
        agent_router: AgentRouter,
        plan_builder: PlanBuilder | None = None,
        orchestrator_factory: Callable[[TaskManager, AgentRouter], Orchestrator] | None = None,
        workflow_event_log: WorkflowEventLog | None = None,
        project_id: str | None = None,
        workflow_event_persistence: WorkflowEventPersistenceAdapter | None = None,
        deliverable_dir: str | None = None,
        sandbox: "WorkspaceSandbox | None" = None,
        clarifications: str | None = None,
        release_requested: bool = False,
        release_version: str | None = None,
        auto_release: bool = False,
    ):
        if agent_router is None:
            raise ValueError("agent_router cannot be None")
        if workflow_event_log is not None and not isinstance(workflow_event_log, WorkflowEventLog):
            raise TypeError("workflow_event_log must be a WorkflowEventLog or None")
        if workflow_event_persistence is not None and not isinstance(
            workflow_event_persistence, WorkflowEventPersistenceAdapter
        ):
            raise TypeError(
                "workflow_event_persistence must be a WorkflowEventPersistenceAdapter or None"
            )
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise ValueError("project_id must be a non-empty string or None")
        if deliverable_dir is not None and (
            not isinstance(deliverable_dir, str) or not deliverable_dir.strip()
        ):
            raise ValueError("deliverable_dir must be a non-empty string or None")
        if clarifications is not None and not isinstance(clarifications, str):
            raise TypeError("clarifications must be a string or None")
        if not isinstance(release_requested, bool):
            raise TypeError("release_requested must be a bool")
        if release_version is not None and (
            not isinstance(release_version, str) or not release_version.strip()
        ):
            raise ValueError("release_version must be a non-empty string or None")
        if not isinstance(auto_release, bool):
            raise TypeError("auto_release must be a bool")
        self.agent_router = agent_router
        self.plan_builder = plan_builder if plan_builder is not None else PlanBuilder()
        self.orchestrator_factory = orchestrator_factory if orchestrator_factory is not None else self._default_orchestrator_factory
        self.last_plan: dict[str, Any] | None = None
        self.last_task_manager: TaskManager | None = None
        self.last_result: ProjectResult | None = None
        self.last_requirement_analysis: str | None = None
        self.last_delivery: dict[str, Any] | None = None
        self.last_acceptance: dict[str, Any] | None = None
        self.deliverable_dir = deliverable_dir.strip().strip("/") if deliverable_dir else None
        self.sandbox = sandbox
        self.clarifications = clarifications
        self.release_requested = release_requested
        self.release_version = release_version.strip() if release_version else None
        self.auto_release = auto_release
        self._workflow_event_log = workflow_event_log
        self._workflow_event_persistence = workflow_event_persistence
        self._project_id = project_id
        if self._workflow_event_log is not None and workflow_event_persistence is not None:
            self._workflow_event_log.set_persistence_sink(workflow_event_persistence)

    @property
    def workflow_event_log(self) -> WorkflowEventLog | None:
        return self._workflow_event_log

    @property
    def workflow_event_persistence(self) -> WorkflowEventPersistenceAdapter | None:
        return self._workflow_event_persistence

    @staticmethod
    def _default_orchestrator_factory(task_manager: TaskManager, agent_router: AgentRouter) -> Orchestrator:
        return Orchestrator(task_manager=task_manager, agent_router=agent_router)

    def _ensure_workflow_event_log(self) -> WorkflowEventLog | None:
        if self._workflow_event_log is None and self._workflow_event_persistence is not None:
            self._workflow_event_log = WorkflowEventLog(
                persistence_sink=self._workflow_event_persistence
            )
        return self._workflow_event_log

    def _resolved_project_id(self) -> str | None:
        if self._project_id is not None:
            return self._project_id
        if self.last_plan is not None:
            value = self.last_plan.get("project_id")
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _emit_project_event(self, event_type: str, *, payload: dict[str, Any] | None = None) -> None:
        log = self._ensure_workflow_event_log()
        if log is None:
            return
        project_id = self._resolved_project_id()
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id is required when workflow_event_log is enabled")
        log.append(WorkflowEvent(event_id=str(uuid4()), event_type=event_type, project_id=project_id, task_id=None, occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), payload=payload or {}))

    @staticmethod
    def _restore_tool_execution_history(task_manager: TaskManager, history: ToolExecutionHistory | None) -> None:
        tasks = {task.id: task for task in task_manager.get_all_tasks()}
        for task in tasks.values():
            task.context.pop("tool_execution_history", None)
        if history is None:
            return
        records_by_task: dict[str, list[dict[str, Any]]] = {}
        for record in history.to_dict():
            task_id = record.get("task_id")
            if not isinstance(task_id, str) or task_id not in tasks:
                raise ValueError(f"persisted tool execution history references unknown task: {task_id}")
            records_by_task.setdefault(task_id, []).append(record)
        for task_id, records in records_by_task.items():
            task_history = ToolExecutionHistory.from_dict(records)
            tasks[task_id].context["tool_execution_history"] = task_history.to_context_dict()

    def _rehydrate_workflow_event_log(self, project_id: str, event_persistence: WorkflowEventPersistenceAdapter | None) -> None:
        """Restore events for recovery without making recovery itself durable."""
        if event_persistence is None:
            return
        if not isinstance(event_persistence, WorkflowEventPersistenceAdapter):
            raise TypeError("event_persistence must be a WorkflowEventPersistenceAdapter or None")
        self._workflow_event_log = event_persistence.load_log()
        self._workflow_event_persistence = event_persistence
        self._project_id = project_id

    def _enable_runtime_event_persistence(self) -> None:
        if self._workflow_event_log is not None and self._workflow_event_persistence is not None:
            self._workflow_event_log.set_persistence_sink(self._workflow_event_persistence)

    def create_plan(self, requirement: str) -> dict[str, Any]:
        if not isinstance(requirement, str):
            raise TypeError("requirement must be a string")
        if not requirement.strip():
            raise ValueError("requirement cannot be empty")
        analyst = self.agent_router.get_agent("analyst")
        if analyst is not None:
            self.last_requirement_analysis = self._run_requirement_analysis(requirement)
        planner = self.agent_router.get_agent("planner")
        planning_task = Task(id=self.PLANNER_TASK_ID, title="Generate project development plan", description=requirement, role="planner", status="ready")
        # The analysis rides in the task context, never in the description:
        # mechanical path-constraint extraction must see ONLY the user's
        # original text, so analyst-side directory hallucinations cannot
        # become enforced constraints.
        planning_task.context["requirement_analysis"] = self.last_requirement_analysis or ""
        result = planner.run(planning_task)
        if not isinstance(result, dict):
            raise TypeError("PlannerAgent must return a dictionary")
        plan = result.get("plan")
        if not isinstance(plan, dict):
            raise ValueError("PlannerAgent result does not contain a valid plan")
        validate_plan(plan)
        self.last_plan = plan
        return plan

    def _run_requirement_analysis(self, requirement: str) -> str:
        """Normalize the customer requirement into a structured draft spec.

        Works for both ends of the clarity spectrum: explicit feature lists
        are restructured faithfully, while one-line requirements get explicit
        【假设】-labeled inference plus open questions for the customer.
        The draft is quality-checked (sections present, 必须-level acceptance
        criteria) with one corrective retry before planning proceeds.
        """
        analyst = self.agent_router.get_agent("analyst")
        result = run_quality_checked_analysis(
            analyst,
            requirement=requirement,
            clarifications=self.clarifications or None,
        )
        analysis = result.message
        if not isinstance(analysis, str) or not analysis.strip():
            raise ValueError("Requirement analyst returned an empty analysis")
        self._emit_project_event(
            "project.requirement_analyzed",
            payload={
                "task_id": self.ANALYST_TASK_ID,
                "chars": len(analysis),
                "attempts": result.data.get("attempts", 1),
                "quality_ok": (result.data.get("quality") or {}).get("ok", False),
            },
        )
        return analysis

    def build_task_manager(self, plan: dict[str, Any]) -> TaskManager:
        if not isinstance(plan, dict):
            raise TypeError("plan must be a dictionary")
        task_manager = self.plan_builder.build_task_manager(plan)
        self.last_task_manager = task_manager
        return task_manager

    def create_orchestrator(self, task_manager: TaskManager) -> Orchestrator:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        return self.orchestrator_factory(task_manager, self.agent_router)

    def execute(self, task_manager: TaskManager, *, state_change_hook: Callable[[TaskManager], None] | None = None) -> ProjectResult:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        if state_change_hook is not None and not callable(state_change_hook):
            raise TypeError("state_change_hook must be callable or None")
        self.last_task_manager = task_manager
        self._enable_runtime_event_persistence()
        orchestrator = self.create_orchestrator(task_manager)
        log = self._ensure_workflow_event_log()
        if log is not None:
            orchestrator.set_workflow_event_log(log, project_id=self._resolved_project_id())
        set_hook = getattr(orchestrator, "set_state_change_hook", None)
        if state_change_hook is not None and callable(set_hook):
            set_hook(state_change_hook)
        orchestrator.run()
        project_name = None
        if self.last_plan is not None:
            value = self.last_plan.get("project")
            if isinstance(value, str):
                project_name = value
        result = ProjectResult.from_task_manager(task_manager, project=project_name)
        delivery = self._run_delivery_phase(task_manager, project=project_name)
        if delivery is not None and delivery.get("acceptance") is not None:
            result = ProjectResult(
                project=result.project,
                success=result.success,
                status=result.status,
                total_tasks=result.total_tasks,
                completed_tasks=result.completed_tasks,
                failed_tasks=result.failed_tasks,
                blocked_tasks=result.blocked_tasks,
                completed_task_ids=result.completed_task_ids,
                acceptance_verdict=delivery["acceptance"]["verdict"],
            )
        self.last_result = result
        return result

    def _run_delivery_phase(self, task_manager: TaskManager, *, project: str | None) -> dict[str, Any] | None:
        """Produce the integration evidence, document set and delivery manifest.

        Runs after every product task. First the product-level integration &
        regression suite executes on the finished deliverable (with a bounded
        developer-rework loop on failure); then a DocWriter turns the
        whole-project context (requirement analysis, plan, per-task reports,
        test and integration evidence) into the standard documents inside the
        sandbox, and a deterministic manifest lists every deliverable file
        with checksums. Packaging is gated on the integration verdict: a red
        suite is reported honestly and never packaged. No-op when no
        doc_writer is registered.
        """
        get_agent = getattr(self.agent_router, "get_agent", None)
        doc_writer = get_agent("doc_writer") if callable(get_agent) else None
        if doc_writer is None:
            return None
        if self.sandbox is not None and hasattr(doc_writer, "sandbox"):
            doc_writer.sandbox = self.sandbox
        if self.sandbox is not None:
            manifest_root = self.sandbox.resolve(self.deliverable_dir or ".")
        else:
            manifest_root = resolve_workspace_path(self.deliverable_dir or ".")
        integration = self._run_integration_phase(manifest_root)
        qa: dict[str, Any] | None = None
        if integration is None or integration["status"] != "failed":
            qa = self._run_qa_phase(manifest_root, integration)
        dependency_scan = scan_deliverable_dependencies(manifest_root)
        delivery_task = Task(
            id=self.DELIVERY_TASK_ID,
            title="生成交付文档与交付清单",
            description="汇总项目上下文，撰写标准交付文档集（需求/设计/测试/部署/用户手册）。",
            role="doc_writer",
            status="ready",
        )
        delivery_task.context["requirement_analysis"] = self.last_requirement_analysis or ""
        delivery_task.context["deliverable_dir"] = self.deliverable_dir or ""
        delivery_task.context["plan_summary"] = {
            "project": (self.last_plan or {}).get("project", ""),
            "summary": (self.last_plan or {}).get("summary", ""),
        }
        delivery_task.context["task_digest"] = self._task_digest(task_manager)
        if integration is not None:
            delivery_task.context["integration_evidence"] = self._integration_evidence_digest(integration)
        if qa is not None:
            delivery_task.context["qa_evidence"] = self._qa_evidence_digest(qa)
        delivery_task.context["dependency_scan"] = dependency_scan
        outcome = doc_writer.run(delivery_task)
        docs: Any = None
        if isinstance(outcome, AgentResult):
            if outcome.status == "completed":
                docs = outcome.data.get("docs", [])
        elif isinstance(outcome, dict):
            # Legacy-style agents may return plain result dictionaries.
            docs = outcome.get("docs")
        if docs is None:
            # Documentation is part of the delivery, but a doc-writer failure
            # must not invalidate the finished product: record and continue.
            print("[Delivery] 文档生成未完成，交付清单已跳过")
            self._emit_project_event("project.delivery_skipped", payload={"reason": "doc_writer did not complete"})
            return None
        docs_root = (self.deliverable_dir or ".") + "/docs"
        acceptance = self._run_acceptance_phase(manifest_root, project=project)
        delivery = {
            "docs_root": docs_root,
            "docs": docs,
            "manifest": None,
            "acceptance": acceptance,
            "integration": integration,
            "qa": qa,
            "dependency_scan": dependency_scan,
            "release": None,
        }
        self.last_delivery = delivery
        self.last_acceptance = acceptance
        verdict_note = f"，验收 {acceptance['verdict'].upper()}" if acceptance else ""
        release: dict[str, Any] | None = None
        if self.release_requested and (integration is None or integration["status"] != "failed"):
            if qa is not None and qa.get("verdict") == "QA_FAILED":
                delivery["release"] = {"status": "blocked", "reason": "QA verdict is QA_FAILED"}
                self._emit_project_event("project.release_blocked", payload={"reason": "qa_failed"})
                print("[Release] QA 对抗测试未通过（QA_FAILED），发布已门禁")
            else:
                release = self._run_release_phase(manifest_root, delivery, project=project)
                delivery["release"] = release
        # The manifest is written after the release phase so RELEASE_NOTES.md
        # and release_log.json are part of the checksummed deliverable set.
        manifest_path = write_delivery_manifest(manifest_root, project=project)
        delivery["manifest"] = str(manifest_path)
        payload = {
            "docs_root": docs_root,
            "manifest": str(manifest_path),
            "document_count": len(delivery["docs"]),
        }
        if acceptance is not None:
            payload["acceptance_verdict"] = acceptance["verdict"]
            self._emit_project_event("project.acceptance_completed", payload=acceptance)
        if integration is not None:
            payload["integration_status"] = integration["status"]
            payload["integration_rounds"] = integration["rounds"]
        if qa is not None:
            payload["qa_verdict"] = qa.get("verdict")
        if release is not None:
            payload["release_status"] = release.get("status")
        self._emit_project_event(
            "project.delivery_completed",
            payload=payload,
        )
        verdict_note = f"，验收 {acceptance['verdict'].upper()}" if acceptance else ""
        if integration is not None and integration["status"] == "failed":
            # A red regression suite is reported honestly and never packaged:
            # shipping a broken deliverable is not a delivery.
            delivery["package"] = None
            delivery["smoke"] = None
            print(f"[Delivery] 集成回归未通过（{integration['rounds']} 轮修复后仍失败），已跳过打包{verdict_note}")
            return delivery
        bundle = create_deployment_bundle(
            manifest_root,
            output_dir=manifest_root.parent if manifest_root.parent != manifest_root else None,
            project=project or "ai-team-delivery",
            smoke=True,
        )
        delivery["package"] = {
            "archive": bundle["bundle"],
            "files": bundle["files"],
            "checksum": bundle["checksum"],
        }
        if release is not None and release.get("status") == "released":
            release["package"] = {"archive": bundle["bundle"], "checksum": bundle["checksum"]}
        delivery["smoke"] = bundle["smoke"]
        print(f"[Delivery] 交付包 {bundle['bundle']} ({bundle['files']} 文件, 冒烟 {bundle['smoke']['status']}){verdict_note}")
        return delivery

    def _run_acceptance_phase(self, manifest_root: Path, *, project: str | None) -> dict[str, Any] | None:
        """Verify product-requirement conformance over the delivery artifacts.

        Deterministic requirement traceability: every REQ-xxx the analyst
        numbered must be referenced by the requirements document and the test
        report (必须-level), with acceptance criteria present. The verdict is
        reported but never fails the delivery phase itself.
        """
        analysis = self.last_requirement_analysis or ""
        entries = parse_requirement_entries(analysis)
        if not entries:
            return None
        docs_dir = Path(manifest_root) / "docs"
        sources: dict[str, str] = {}
        for filename, source_name in (
            ("requirements.md", "requirements_doc"),
            ("design.md", "design_doc"),
            ("test_report.md", "test_report"),
            ("user_manual.md", "user_manual"),
        ):
            doc_path = docs_dir / filename
            sources[source_name] = (
                doc_path.read_text(encoding="utf-8", errors="replace")
                if doc_path.is_file()
                else ""
            )
        matrix = build_traceability_matrix(entries, sources=sources)
        verdict = acceptance_verdict(entries, matrix)
        report_path = write_acceptance_report(docs_dir, entries, matrix, verdict, project=project)
        return {
            "verdict": verdict["verdict"],
            "gaps": verdict["gaps"],
            "warnings": verdict["warnings"],
            "total_requirements": verdict["total_requirements"],
            "report": str(report_path),
        }

    def _run_integration_phase(self, manifest_root: Path) -> dict[str, Any]:
        """Product-level integration & regression gate with bounded rework.

        Each evaluation runs the deliverable's full test suite from a fresh
        copy plus the deterministic static-quality gate (ruff enforced;
        mypy opt-in). A failure in either feeds developer rework tasks
        (carrying fenced failure evidence) through the canonical
        TaskWorkflow, then both run again. Rounds are bounded by
        AI_TEAM_INTEGRATION_MAX_ROUNDS (default 2, 0 disables rework but
        still evaluates once); exhaustion is reported honestly as FAILED
        and gates packaging. A deliverable without test files yields a
        skipped suite record so the documentation can state the absence of
        regression evidence; the static gate (AI_TEAM_STATIC_GATE, default
        on) still applies.
        """
        timeout = self._env_float("AI_TEAM_INTEGRATION_TIMEOUT", DEFAULT_INTEGRATION_TIMEOUT)
        max_rounds = self._env_int("AI_TEAM_INTEGRATION_MAX_ROUNDS", 2)
        if max_rounds < 0:
            raise ValueError("AI_TEAM_INTEGRATION_MAX_ROUNDS must be >= 0")
        static_enabled = self._env_int("AI_TEAM_STATIC_GATE", 1) == 1
        run_mypy = self._env_int("AI_TEAM_STATIC_MYPY", 0) == 1
        enforce_mypy = self._env_int("AI_TEAM_STATIC_MYPY_ENFORCE", 0) == 1
        static_timeout = self._env_float("AI_TEAM_STATIC_TIMEOUT", DEFAULT_STATIC_TIMEOUT)

        def evaluate() -> tuple[dict[str, Any], dict[str, Any] | None]:
            suite = run_integration_suite(manifest_root, timeout=timeout)
            static = (
                run_static_quality_gate(
                    manifest_root,
                    timeout=static_timeout,
                    run_mypy=run_mypy,
                    enforce_mypy=enforce_mypy,
                )
                if static_enabled
                else None
            )
            return suite, static

        def failed(static: dict[str, Any] | None) -> bool:
            return static is not None and static.get("status") == "failed"

        suite, static = evaluate()
        self._emit_project_event(
            "project.integration_started",
            payload={
                "status": suite["status"],
                "test_files": len(suite.get("test_files") or []),
                "static_status": static.get("status") if static is not None else None,
            },
        )
        if suite["status"] != "failed" and not failed(static):
            self._emit_project_event(
                "project.integration_completed",
                payload={
                    "status": suite["status"],
                    "rounds": 0,
                    "summary": suite.get("summary"),
                    "static_status": static.get("status") if static is not None else None,
                },
            )
            note = "（交付物无测试文件）" if suite["status"] == "skipped" else ""
            print(f"[Integration] 集成回归 {suite['status'].upper()}{note}（{suite.get('command') or '-'}）")
            return {
                "status": suite["status"],
                "rounds": 0,
                "rework_rounds": [],
                "suite": suite,
                "static": static,
            }

        rework_rounds: list[dict[str, Any]] = []
        for round_no in range(1, max_rounds + 1):
            rework_rounds.append(self._run_rework_round(suite, round_no, static=static))
            suite, static = evaluate()
            if suite["status"] != "failed" and not failed(static):
                break
        final_status = (
            "failed"
            if suite["status"] == "failed" or failed(static)
            else suite["status"]
        )
        payload = {
            "status": final_status,
            "rounds": len(rework_rounds),
            "summary": suite.get("summary"),
            "static_status": static.get("status") if static is not None else None,
        }
        if final_status == "failed":
            self._emit_project_event("project.integration_failed", payload=payload)
            print(f"[Integration] 集成回归 FAILED（{len(rework_rounds)} 轮修复后仍未通过）")
        else:
            self._emit_project_event("project.integration_completed", payload=payload)
            print(f"[Integration] 集成回归 PASSED（第 {len(rework_rounds)} 轮修复后通过）")
        return {
            "status": final_status,
            "rounds": len(rework_rounds),
            "rework_rounds": rework_rounds,
            "suite": suite,
            "static": static,
        }

    def _run_rework_round(self, suite: dict[str, Any], round_no: int, *, static: dict[str, Any] | None = None) -> dict[str, Any]:
        """One bounded rework round through the canonical developer workflow.

        The rework task carries the fenced suite-failure (and static-gate)
        evidence and executes through the same TaskWorkflow as product tasks
        (developer tool loop + tester + reviewer gates). Suite and static
        re-evaluation afterwards is the only pass/fail authority; rework
        exceptions are recorded as evidence.
        """
        evidence: dict[str, Any] = {
            "command": suite.get("command") or "",
            "exit_code": suite.get("exit_code"),
            "summary": suite.get("summary"),
            "failed_tests": suite.get("failed_tests") or [],
            "output_tail": (suite.get("output_tail") or "")[-2500:],
        }
        static_failed = False
        if static is not None:
            static_failed = static.get("status") == "failed"
            evidence["static"] = {
                "status": static.get("status"),
                "tools": {
                    name: {
                        "status": record.get("status"),
                        "enforced": record.get("enforced"),
                        "output_tail": (record.get("output_tail") or "")[-1200:],
                    }
                    for name, record in (static.get("tools") or {}).items()
                },
            }
        deliverable = self.deliverable_dir or "工作区根目录"
        static_note = "静态质量门禁存在未通过的强制项，请一并修复。" if static_failed else ""
        description = (
            f"产品级集成回归测试失败（第 {round_no} 轮修复）。交付目录: {deliverable}。{static_note}"
            f"请先在该目录内复现失败（运行下方证据中的测试命令），修复缺陷后重跑完整测试套件直到通过。"
            f"所有修改必须限制在交付目录内；不得删除或弱化测试断言来让测试通过。\n\n"
            + untrusted_content("integration.failure", evidence)
        )
        task = Task(
            id=f"REWORK-{round_no:03d}",
            title=f"集成回归修复（第 {round_no} 轮）",
            description=description,
            role="developer",
            status="ready",
        )
        task.context["integration_failure"] = evidence
        rework_manager = TaskManager([task])
        rework_orchestrator = self.create_orchestrator(rework_manager)
        log = self._ensure_workflow_event_log()
        if log is not None:
            project_id = self._resolved_project_id()
            if isinstance(project_id, str) and project_id.strip():
                rework_orchestrator.set_workflow_event_log(log, project_id=project_id)
        error: str | None = None
        try:
            rework_orchestrator.execute_task(task.id)
        except Exception as exc:  # a failed rework round is evidence, not a crash
            error = f"{type(exc).__name__}: {exc}"
        rework_task = rework_manager.get_task(task.id)
        return {"round": round_no, "task_id": task.id, "status": str(rework_task.status), "error": error}

    @staticmethod
    def _integration_evidence_digest(integration: dict[str, Any]) -> dict[str, Any]:
        """Compact the integration record for the DocWriter context."""
        suite = integration.get("suite")
        digest: dict[str, Any] = {
            "status": integration.get("status"),
            "rounds": integration.get("rounds", 0),
        }
        if isinstance(suite, dict):
            digest["suite"] = {
                "command": suite.get("command"),
                "exit_code": suite.get("exit_code"),
                "duration_seconds": suite.get("duration_seconds"),
                "summary": suite.get("summary"),
                "failed_tests": (suite.get("failed_tests") or [])[:10],
                "output_tail": (suite.get("output_tail") or "")[-2000:],
            }
        static = integration.get("static")
        if isinstance(static, dict):
            digest["static"] = {
                "status": static.get("status"),
                "tools": {
                    name: {"status": record.get("status"), "enforced": record.get("enforced")}
                    for name, record in (static.get("tools") or {}).items()
                    if isinstance(record, dict)
                },
            }
        return digest

    def _run_qa_phase(self, manifest_root: Path, integration: dict[str, Any] | None) -> dict[str, Any] | None:
        """Product-level adversarial QA, independent from the developers.

        Runs once after the integration gate and before documentation. No-op
        when no qa agent is registered. The QA verdict never invalidates the
        finished product; a QA_FAILED verdict blocks the release honestly
        while packaging still proceeds.
        """
        get_agent = getattr(self.agent_router, "get_agent", None)
        qa_agent = get_agent("qa") if callable(get_agent) else None
        if qa_agent is None:
            return None
        files = sorted(
            path.relative_to(manifest_root).as_posix()
            for path in manifest_root.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and not path.name.endswith(".pyc")
        )[:100]
        integration_summary: dict[str, Any] | None = None
        if isinstance(integration, dict):
            suite = integration.get("suite")
            integration_summary = {
                "status": integration.get("status"),
                "summary": suite.get("summary") if isinstance(suite, dict) else None,
            }
        qa_task = Task(
            id=self.QA_TASK_ID,
            title="产品级对抗测试（QA）",
            description=(
                "以对抗方式验证交付物：边界与非法输入、异常路径、重复与交错执行、"
                "文档一致性与稳定性。最终结论第一行输出 QA_PASSED 或 QA_FAILED。"
            ),
            role="qa",
            status="ready",
        )
        qa_task.context["deliverable_dir"] = self.deliverable_dir or "."
        qa_task.context["product_summary"] = (self.last_requirement_analysis or "")[:2000]
        qa_task.context["integration_summary"] = integration_summary
        qa_task.context["files"] = files
        try:
            outcome = qa_agent.run(qa_task)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._emit_project_event(
                "project.qa_completed",
                payload={"verdict": "unknown", "status": "error", "error": error},
            )
            print(f"[QA] 对抗测试执行失败：{error}")
            return {"verdict": "unknown", "status": "error", "error": error}
        message = getattr(outcome, "message", "")
        data = getattr(outcome, "data", None)
        qa_data = data.get("qa") if isinstance(data, dict) and isinstance(data.get("qa"), dict) else {}
        verdict = qa_data.get("verdict") or parse_qa_verdict(str(message or ""))
        status = getattr(outcome, "status", "completed")
        record = {
            "verdict": verdict,
            "status": str(status),
            "message_head": str(message or "")[:1500],
        }
        self._emit_project_event(
            "project.qa_completed",
            payload={"verdict": verdict, "status": str(status)},
        )
        print(f"[QA] 对抗测试结论：{str(verdict).upper()}")
        return record

    @staticmethod
    def _qa_evidence_digest(qa: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(qa, dict):
            return None
        return {
            "verdict": qa.get("verdict"),
            "status": qa.get("status"),
            "message_head": str(qa.get("message_head") or "")[:1200],
        }

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"environment variable {name} must be an integer: {raw!r}") from exc

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            return default
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"environment variable {name} must be a number: {raw!r}") from exc
        if value <= 0:
            raise ValueError(f"environment variable {name} must be positive: {raw!r}")
        return value

    def _run_release_phase(self, manifest_root: Path, delivery: dict[str, Any], *, project: str | None) -> dict[str, Any] | None:
        """Version, release notes, host-owned git anchor and release log.

        Runs after acceptance and before the manifest/packaging so the release
        artifacts are part of the checksummed deliverable set. The release
        never invalidates the finished product: deterministic failures are
        recorded honestly via project.release_failed.
        """
        try:
            parsed_entries = parse_requirement_entries(self.last_requirement_analysis or "")
        except ValueError:
            parsed_entries = []
        requirement_entries = [
            {"id": entry.req_id, "title": entry.title or "", "priority": entry.priority or "未标注"}
            for entry in parsed_entries
        ]
        integration = delivery.get("integration")
        integration_summary: dict[str, Any] | None = None
        if isinstance(integration, dict):
            suite = integration.get("suite")
            static = integration.get("static")
            integration_summary = {
                "status": integration.get("status"),
                "rounds": integration.get("rounds", 0),
                "summary": suite.get("summary") if isinstance(suite, dict) else None,
                "static_status": static.get("status") if isinstance(static, dict) else None,
            }
        result = self.last_result
        context: dict[str, Any] = {
            "project": project,
            "deliverable_dir": self.deliverable_dir or ".",
            "requirement_entries": requirement_entries,
            "acceptance": delivery.get("acceptance"),
            "integration": integration_summary,
            "qa": {"verdict": (delivery.get("qa") or {}).get("verdict")},
            "docs": [
                doc.get("document") for doc in delivery.get("docs", []) if isinstance(doc, dict)
            ],
            "task_stats": {
                "total": getattr(result, "total_tasks", None),
                "completed": getattr(result, "completed_tasks", None),
            },
        }
        request = ReleaseRequest(
            deliverable_root=str(manifest_root),
            project=project,
            version=self.release_version,
            auto_release=self.auto_release,
        )
        try:
            outcome = perform_release(
                request,
                git_service=HostGitOperationService(sandbox=self.sandbox),
                context=context,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._emit_project_event("project.release_failed", payload={"error": error})
            print(f"[Release] 发布失败：{error}")
            return {"status": "failed", "error": error}
        if outcome.get("status") == "released":
            self._emit_project_event(
                "project.release_completed",
                payload={key: outcome.get(key) for key in ("version", "tag", "commit")},
            )
            print(
                f"[Release] 已发布 {outcome.get('tag')}"
                f"（commit {str(outcome.get('commit'))[:12]}，锚点=交付目录 git 仓库）"
            )
        else:
            self._emit_project_event(
                "project.release_pending",
                payload={"version": outcome.get("version"), "reason": outcome.get("reason")},
            )
            print(
                f"[Release] 发布待确认 v{outcome.get('version')}"
                f"（未写发布记录；--auto-release 可跳过确认）"
            )
        return outcome

    def _task_digest(self, task_manager: TaskManager) -> list[dict[str, Any]]:
        digest: list[dict[str, Any]] = []
        for task in task_manager.get_all_tasks():
            message = ""
            tests: list[Any] = []
            result_payload = task.result
            if isinstance(result_payload, dict):
                message = str(result_payload.get("message") or result_payload.get("summary") or "")
                data = result_payload.get("data")
                if isinstance(data, dict):
                    tests_value = data.get("tests")
                    if isinstance(tests_value, list):
                        tests = tests_value
            elif result_payload is not None:
                message = str(result_payload)
            digest.append({
                "id": task.id,
                "role": task.role,
                "title": task.title,
                "status": str(task.status),
                "report": message.replace("\n", " ")[:1500],
                "test_evidence_count": len(tests),
            })
        return digest

    def resume(self, task_manager: TaskManager | None = None) -> ProjectResult:
        manager = task_manager if task_manager is not None else self.last_task_manager
        if manager is None:
            raise ValueError("no in-memory task manager is available to resume")
        if not isinstance(manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        self._emit_project_event("project.resumed", payload={"source": "memory"})
        return self.execute(manager)

    def resume_persisted(self, project_id: str, adapter: ProjectPersistenceAdapter, *, event_persistence: WorkflowEventPersistenceAdapter | None = None) -> ProjectResult:
        """Restore persisted project state without starting execution."""
        if not isinstance(adapter, ProjectPersistenceAdapter):
            raise TypeError("adapter must be a ProjectPersistenceAdapter")
        snapshot = adapter.load(project_id)
        self.last_plan = snapshot.plan
        self.last_task_manager = snapshot.task_manager
        self._restore_tool_execution_history(snapshot.task_manager, snapshot.tool_execution_history)
        self.last_result = snapshot.result
        self._rehydrate_workflow_event_log(project_id, event_persistence)
        self._emit_project_event("project.resumed", payload={"source": "persistence", "project_id": project_id})
        return snapshot.result or ProjectResult.from_task_manager(snapshot.task_manager, project=(snapshot.plan or {}).get("project") if snapshot.plan else None)

    def audit_persisted(self, project_id: str, adapter: ProjectPersistenceAdapter) -> ToolExecutionAudit:
        if not isinstance(adapter, ProjectPersistenceAdapter):
            raise TypeError("adapter must be a ProjectPersistenceAdapter")
        return adapter.audit(project_id)

    def audit_consistency_persisted(self, project_id: str, adapter: ProjectPersistenceAdapter) -> dict[str, Any]:
        if not isinstance(adapter, ProjectPersistenceAdapter):
            raise TypeError("adapter must be a ProjectPersistenceAdapter")
        return adapter.audit_consistency(project_id)

    def continue_persisted(self, project_id: str, adapter: ProjectPersistenceAdapter, *, event_persistence: WorkflowEventPersistenceAdapter | None = None) -> ProjectResult:
        """Restore a persisted project and execute only its unfinished work."""
        if not isinstance(adapter, ProjectPersistenceAdapter):
            raise TypeError("adapter must be a ProjectPersistenceAdapter")
        snapshot = adapter.load(project_id)
        self.last_plan = snapshot.plan
        self.last_task_manager = snapshot.task_manager
        self._restore_tool_execution_history(snapshot.task_manager, snapshot.tool_execution_history)
        self._rehydrate_workflow_event_log(project_id, event_persistence)
        self._enable_runtime_event_persistence()
        project_name = None
        if self.last_plan is not None:
            value = self.last_plan.get("project")
            if isinstance(value, str):
                project_name = value

        def persist_boundary(manager: TaskManager) -> None:
            boundary_result = ProjectResult.from_task_manager(manager, project=project_name)
            adapter.update(project_id, plan=self.last_plan, task_manager=manager, result=boundary_result)

        result = self.execute(snapshot.task_manager, state_change_hook=persist_boundary)
        persisted = adapter.load(project_id)
        if persisted.result != result or any(persisted.task_manager.get_task(task.id).status != task.status for task in self.last_task_manager.get_all_tasks()):
            adapter.update(project_id, plan=self.last_plan, task_manager=self.last_task_manager, result=result)
        return result

    def run(self, requirement: str) -> ProjectResult:
        plan = self.create_plan(requirement)
        task_manager = self.build_task_manager(plan)
        return self.execute(task_manager)
