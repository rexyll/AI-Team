from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from runtime.static_gate import write_static_report
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
from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from agents.analyst import run_quality_checked_analysis
from runtime.delivery_manifest import write_delivery_manifest
from runtime.deployment import create_deployment_bundle
from runtime.plan_builder import PlanBuilder
from runtime.release_anchor import create_release_anchor
from runtime.cost_report import build_cost_report, write_cost_report
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_validator import validate_plan
from runtime.tool_execution_audit import ToolExecutionAudit
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter
from security.workspace import WorkspaceSandbox, resolve_workspace_path


def _EMPTY_COST_REGISTRY():
    from runtime.model_cost import ModelCostRateRegistry

    return ModelCostRateRegistry()


class ProjectOrchestrator:
    """Project-level orchestration entry point."""

    PLANNER_TASK_ID = "PLAN-001"
    ANALYST_TASK_ID = "REQ-ANALYSIS"
    DELIVERY_TASK_ID = "DELIVERY-001"

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
        static_gate: Callable[[Path], dict[str, Any]] | None = None,
        release_anchor: Callable[..., dict[str, Any]] | None = None,
        usage_ledger: Any = None,
        cost_rate_registry: Any = None,
        workspace_isolation: bool = True,
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
        self.agent_router = agent_router
        self.workspace_isolation = workspace_isolation
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
        if static_gate is not None and not callable(static_gate):
            raise TypeError("static_gate must be callable or None")
        self.static_gate = static_gate
        if release_anchor is not None and not callable(release_anchor):
            raise TypeError("release_anchor must be callable or None")
        self.release_anchor = release_anchor
        self.usage_ledger = usage_ledger
        self._cost_project_id = project_id
        self.cost_rate_registry = cost_rate_registry
        self.last_cost_report: Any = None
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

    def _default_orchestrator_factory(self, task_manager: TaskManager, agent_router: AgentRouter) -> Orchestrator:
        return Orchestrator(
            task_manager=task_manager,
            agent_router=agent_router,
            workspace_isolation=self.workspace_isolation,
        )

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
        gate_status = None
        if self.static_gate is not None or (delivery is not None and "static_gate" in delivery):
            gate_status = (delivery or {}).get("static_gate", {}).get("status", "unverified")
        if delivery is not None and delivery.get("acceptance") is not None:
            result = ProjectResult(
                project=result.project,
                success=result.success and gate_status in (None, "passed"),
                status=result.status if gate_status in (None, "passed") else "failed",
                total_tasks=result.total_tasks,
                completed_tasks=result.completed_tasks,
                failed_tasks=result.failed_tasks,
                blocked_tasks=result.blocked_tasks,
                completed_task_ids=result.completed_task_ids,
                acceptance_verdict=delivery["acceptance"]["verdict"],
                static_gate_verdict=gate_status,
            )
        elif gate_status is not None:
            result = replace(
                result, static_gate_verdict=gate_status,
                success=result.success and gate_status == "passed",
                status=result.status if gate_status == "passed" else "failed",
            )
        self.last_result = result
        return result

    def _run_delivery_phase(self, task_manager: TaskManager, *, project: str | None) -> dict[str, Any] | None:
        """Produce the standard document set and the delivery manifest.

        Runs after every product task: a DocWriter turns the whole-project
        context (requirement analysis, plan, per-task reports and test
        evidence) into the standard documents inside the sandbox, then a
        deterministic manifest lists every deliverable file with checksums.
        No-op when no doc_writer is registered.
        """
        get_agent = getattr(self.agent_router, "get_agent", None)
        doc_writer = get_agent("doc_writer") if callable(get_agent) else None
        if doc_writer is None:
            return None
        if self.sandbox is not None and hasattr(doc_writer, "sandbox"):
            doc_writer.sandbox = self.sandbox
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
        if self.sandbox is not None:
            manifest_root = self.sandbox.resolve(self.deliverable_dir or ".")
        else:
            manifest_root = resolve_workspace_path(self.deliverable_dir or ".")
        docs_root = (self.deliverable_dir or ".") + "/docs"
        gate = self.static_gate(manifest_root) if self.static_gate else None
        if gate is not None:
            write_static_report(manifest_root, gate)
        if self.usage_ledger is not None and self._cost_project_id:
            try:
                report = build_cost_report(
                    self.usage_ledger, self.cost_rate_registry or _EMPTY_COST_REGISTRY(),
                    project_id=self._cost_project_id,
                )
                write_cost_report(manifest_root, report, project=project)
                self.last_cost_report = report
                print(f"[Delivery] 成本报告 ${report.total_cost_usd:.4f} ({report.total_llm_calls()} 次调用) -> docs/cost_report.md")
            except Exception as exc:
                print(f"[Delivery] 成本报告生成失败（不影响交付）: {type(exc).__name__}: {exc}")
        acceptance = self._run_acceptance_phase(manifest_root, project=project)
        manifest_path = write_delivery_manifest(manifest_root, project=project)
        delivery = {
            "docs_root": docs_root,
            "docs": docs,
            "manifest": str(manifest_path),
            "acceptance": acceptance,
        }
        self.last_delivery = delivery
        self.last_acceptance = acceptance
        if gate is not None:
            delivery["static_gate"] = gate
            delivery["release_ready"] = gate["status"] == "passed"
            if gate["status"] != "passed":
                self._emit_project_event("project.delivery_blocked", payload={"static_gate": gate["status"]})
                return delivery
        payload = {
            "docs_root": docs_root,
            "manifest": str(manifest_path),
            "document_count": len(delivery["docs"]),
        }
        if acceptance is not None:
            payload["acceptance_verdict"] = acceptance["verdict"]
            self._emit_project_event("project.acceptance_completed", payload=acceptance)
        self._emit_project_event(
            "project.delivery_completed",
            payload=payload,
        )
        verdict_note = f"，验收 {acceptance['verdict'].upper()}" if acceptance else ""
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
        delivery["smoke"] = bundle["smoke"]
        release_note = ""
        gate_ok = gate is None or gate["status"] == "passed"
        acceptance_ok = acceptance is None or acceptance["verdict"] == "passed"
        if self.release_anchor and gate_ok and acceptance_ok:
            version = (self.last_plan or {}).get("version") or "1.0.0"
            try:
                anchor = create_release_anchor(
                    manifest_root,
                    deliverable_dir=".",
                    project=project or "ai-team-delivery",
                    version=version,
                )
                delivery["release_anchor"] = anchor
                release_note = f"，发布锚点 {anchor['tag']}"
            except (ValueError, OSError) as exc:
                delivery["release_anchor"] = {"error": str(exc)}
                release_note = "，发布锚点失败（不影响交付包）"
        print(f"[Delivery] 交付包 {bundle['bundle']} ({bundle['files']} 文件, 冒烟 {bundle['smoke']['status']}){verdict_note}{release_note}")
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
