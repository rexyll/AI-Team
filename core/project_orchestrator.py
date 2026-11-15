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
from runtime.change_impact import build_incremental_revision
from runtime.dependency_scan import scan_deliverable_dependencies
from runtime.executable_acceptance import (
    evaluate_executable_acceptance,
    load_acceptance_test_specs,
    write_executable_acceptance_report,
)
from runtime.deployment_readiness import (
    run_deployment_readiness,
    sre_evidence_digest,
    write_sre_report,
)
from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from agents.analyst import run_quality_checked_analysis
from agents.qa import parse_qa_verdict
from runtime.delivery_manifest import write_delivery_manifest
from runtime.delivery_sbom import (
    build_delivery_evidence,
    write_build_evidence,
    write_delivery_provenance,
    write_delivery_sbom,
)
from runtime.deployment import create_deployment_bundle
from runtime.integration_verification import (
    DEFAULT_INTEGRATION_TIMEOUT,
    DEFAULT_STATIC_TIMEOUT,
    run_integration_suite,
    run_static_quality_gate,
)
from runtime.knowledge_base import (
    DEFAULT_KNOWLEDGE_LIMIT,
    KnowledgeBase,
    build_knowledge_prompt,
    extract_delivery_knowledge,
)
from runtime.host_git import HostGitOperationService
from runtime.model_usage import ModelUsageLedger
from runtime.monitoring import write_monitoring_contract
from runtime.release import ReleaseRequest, perform_release
from runtime.plan_builder import PlanBuilder
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.project_type import (
    ProjectProfile,
    apply_project_profile,
    classify_task_specialist,
    detect_project_profile,
)
from runtime.release_gate import evaluate_release_gate
from runtime.security_audit import (
    run_security_audit,
    security_evidence_digest,
    write_security_report,
)
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_validator import validate_plan
from runtime.tool_execution_audit import ToolExecutionAudit
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter
from security.prompt_injection import untrusted_content
from security.workspace import (
    WorkspaceSandbox,
    get_default_workspace_folded_prefix,
    resolve_workspace_path,
    workspace_scope,
)
from runtime.project_adapters import (
    DEFAULT_PROJECT_ADAPTER_REGISTRY,
    ProjectAdapterExecutor,
)
from runtime.tool_invocation_service import ToolInvocationService
from runtime.scm_provider import SCMService
from runtime.scm_ci_repair import SCMCIRepairTaskFactory


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
        change_request: str | None = None,
        release_requested: bool = False,
        release_version: str | None = None,
        auto_release: bool = False,
        milestone: str | None = None,
        usage_ledger: ModelUsageLedger | None = None,
        usage_project_id: str | None = None,
        knowledge_base: str | None = None,
        knowledge_query: str | None = None,
        scm_service: SCMService | None = None,
        scm_repository: str | None = None,
        scm_pull_request_number: int | None = None,
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
        if change_request is not None and not isinstance(change_request, str):
            raise TypeError("change_request must be a string or None")
        if not isinstance(release_requested, bool):
            raise TypeError("release_requested must be a bool")
        if release_version is not None and (
            not isinstance(release_version, str) or not release_version.strip()
        ):
            raise ValueError("release_version must be a non-empty string or None")
        if not isinstance(auto_release, bool):
            raise TypeError("auto_release must be a bool")
        if milestone is not None and (
            not isinstance(milestone, str) or not milestone.strip()
        ):
            raise ValueError("milestone must be a non-empty string or None")
        if usage_ledger is not None and not isinstance(usage_ledger, ModelUsageLedger):
            raise TypeError("usage_ledger must be a ModelUsageLedger or None")
        if usage_project_id is not None and (
            not isinstance(usage_project_id, str) or not usage_project_id.strip()
        ):
            raise ValueError("usage_project_id must be a non-empty string or None")
        if usage_project_id is not None and usage_ledger is None:
            raise ValueError("usage_ledger is required when usage_project_id is supplied")
        if knowledge_base is not None and (
            not isinstance(knowledge_base, str) or not knowledge_base.strip()
        ):
            raise ValueError("knowledge_base must be a non-empty string or None")
        if knowledge_query is not None and not isinstance(knowledge_query, str):
            raise TypeError("knowledge_query must be a string or None")
        if scm_service is not None and not isinstance(scm_service, SCMService):
            raise TypeError("scm_service must be an SCMService or None")
        scm_configured = any(
            value is not None
            for value in (scm_service, scm_repository, scm_pull_request_number)
        )
        if scm_configured and (
            scm_service is None
            or not isinstance(scm_repository, str)
            or not scm_repository.strip()
            or not isinstance(scm_pull_request_number, int)
            or isinstance(scm_pull_request_number, bool)
            or scm_pull_request_number < 1
        ):
            raise ValueError(
                "SCM observation requires scm_service, scm_repository and a positive "
                "scm_pull_request_number"
            )
        self.agent_router = agent_router
        self.plan_builder = plan_builder if plan_builder is not None else PlanBuilder()
        self.orchestrator_factory = orchestrator_factory if orchestrator_factory is not None else self._default_orchestrator_factory
        self.last_plan: dict[str, Any] | None = None
        self.last_task_manager: TaskManager | None = None
        self.last_result: ProjectResult | None = None
        self.last_requirement_analysis: str | None = None
        self.last_project_profile: ProjectProfile | None = None
        self.last_delivery: dict[str, Any] | None = None
        self.last_acceptance: dict[str, Any] | None = None
        self.last_revision: dict[str, Any] | None = None
        self.deliverable_dir = deliverable_dir.strip().strip("/") if deliverable_dir else None
        self.sandbox = sandbox
        self.clarifications = clarifications
        self.change_request = change_request
        self.release_requested = release_requested
        self.release_version = release_version.strip() if release_version else None
        self.auto_release = auto_release
        self.milestone = milestone.strip() if milestone else None
        self.usage_ledger = usage_ledger
        self.usage_project_id = usage_project_id
        self.knowledge_base = knowledge_base.strip() if knowledge_base else None
        self.knowledge_query = knowledge_query.strip() if knowledge_query else None
        self.scm_service = scm_service
        self.scm_repository = scm_repository.strip() if scm_repository else None
        self.scm_pull_request_number = scm_pull_request_number
        self.last_scm_observation: dict[str, Any] | None = None
        self.last_scm_repair_proposal: dict[str, Any] | None = None
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

    def _ui_ux_available(self) -> bool:
        """Whether the runtime has a registered ui_ux design agent."""
        has_agent = getattr(self.agent_router, "has_agent", None)
        if callable(has_agent):
            return bool(has_agent("ui_ux"))
        agents = getattr(self.agent_router, "agents", None)
        return isinstance(agents, dict) and agents.get("ui_ux") is not None

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
        # T12: the project profile - deterministic, derived from the customer
        # requirement (reinforced by the analysis and plan text) - decides
        # whether a UI/UX design task is enabled for this project.
        profile = detect_project_profile(requirement, self.last_requirement_analysis or "", plan)
        self.last_project_profile = profile
        ui_ux_available = self._ui_ux_available()
        augmented = apply_project_profile(plan, profile, ui_ux_enabled=ui_ux_available)
        if augmented is not plan:
            validate_plan(augmented)
            plan = augmented
        enabled_specialists = [
            item
            for item in profile.specialists
            if item != "ui_ux" or ui_ux_available
        ]
        if enabled_specialists:
            print(
                f"[Profile] 项目类型 {profile.project_type}，启用专项角色："
                + "、".join(enabled_specialists)
            )
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
            change_request=self.change_request or None,
            knowledge=self._knowledge_prompt(roles=("analyst",)) or None,
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
        workspace_root = (
            self.sandbox.resolve(self.deliverable_dir or ".")
            if self.sandbox is not None
            else resolve_workspace_path(self.deliverable_dir or ".")
        )
        base_prefix = (
            "/".join(self.sandbox.folded_prefix)
            if self.sandbox is not None
            else get_default_workspace_folded_prefix()
        )
        prefix_parts = [part for part in (base_prefix or "").split("/") if part]
        if self.deliverable_dir:
            prefix_parts.extend(
                part for part in self.deliverable_dir.replace("\\", "/").split("/") if part
            )
        folded_prefix = "/".join(prefix_parts) or None
        for task in task_manager.get_all_tasks():
            if task.role == "developer":
                task.context["workspace_root"] = str(workspace_root)
                task.context["workspace_folded_prefix"] = folded_prefix
        # T12: record the project type and match developer tasks to the
        # specialists enabled by the profile. Only task metadata changes;
        # the plan schema and workflow graph stay untouched.
        if self.last_project_profile is not None:
            profile = self.last_project_profile
            for task in task_manager.get_all_tasks():
                task.context["project_type"] = profile.project_type
                if task.role == "developer":
                    specialist = classify_task_specialist(
                        title=task.title,
                        description=task.description,
                        profile=profile,
                    )
                    if specialist is not None:
                        task.context["developer_specialist"] = specialist
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
        delivery = self._run_delivery_phase(task_manager, project=project_name)
        # SCM repair proposals may add a host-approval-gated blocked task during
        # delivery; derive the result only after that task-graph update.
        result = ProjectResult.from_task_manager(task_manager, project=project_name)
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

    def _observe_scm_pull_request(self) -> dict[str, Any] | None:
        """Capture read-only PR/CI/review evidence; never perform SCM writes."""
        if self.scm_service is None:
            return None
        repository = self.scm_repository
        pull_request_number = self.scm_pull_request_number
        if repository is None or pull_request_number is None:
            raise RuntimeError("SCM observation configuration is incomplete")
        try:
            pull_request = self.scm_service.get_pull_request(
                repository, pull_request_number
            )
            head_sha = pull_request["head_sha"]
            ci = self.scm_service.get_ci_status(repository, head_sha)
            review = self.scm_service.get_review_status(
                repository, pull_request_number
            )
            ready = (
                pull_request.get("state") == "open"
                and pull_request.get("merged") is not True
                and ci.get("status") == "success"
                and review.get("status") == "approved"
            )
            return {
                "status": "ready" if ready else "blocked",
                "repository": repository,
                "pull_request_number": pull_request_number,
                "head_sha": head_sha,
                "pull_request_state": pull_request.get("state"),
                "ci_status": ci.get("status", "unknown"),
                "review_status": review.get("status", "unknown"),
            }
        except Exception as exc:
            # SCM is an optional external observation. Keep delivery honest
            # without turning an unavailable remote into a false green state.
            return {
                "status": "unavailable",
                "repository": repository,
                "pull_request_number": pull_request_number,
                "error_type": type(exc).__name__,
            }

    def _propose_scm_ci_repair_task(self, task_manager: TaskManager) -> dict[str, Any] | None:
        """Attach a failed-CI repair proposal as a blocked task; never execute it."""
        self.last_scm_repair_proposal = None
        observation = self.last_scm_observation
        if (
            self.scm_service is None
            or not isinstance(observation, dict)
            or observation.get("ci_status") != "failure"
        ):
            return None
        if self.scm_repository is None or self.scm_pull_request_number is None:
            return {"status": "unavailable", "error_type": "SCMConfigurationError"}
        if not isinstance(self.last_plan, dict) or not isinstance(self.last_plan.get("tasks"), list):
            return {"status": "unavailable", "error_type": "ProjectPlanUnavailable"}

        try:
            proposal = SCMCIRepairTaskFactory(max_repair_rounds=2).propose(
                self.scm_service,
                task_manager,
                repository=self.scm_repository,
                pull_request_number=self.scm_pull_request_number,
            )
            result = proposal.to_dict()
            if proposal.status == "proposed" and proposal.task is not None:
                plan_entry = {
                    "id": proposal.task.id,
                    "title": proposal.task.title,
                    "description": proposal.task.description,
                    "role": proposal.task.role,
                    "dependencies": [],
                }
                candidate_plan = {
                    **self.last_plan,
                    "tasks": [*self.last_plan["tasks"], plan_entry],
                }
                validate_plan(candidate_plan)
                task_manager.add_blocked_task(proposal.task)
                self.last_plan = candidate_plan
                self._emit_project_event(
                    "scm.ci_repair.proposed",
                    payload={
                        "repository": self.scm_repository,
                        "pull_request_number": self.scm_pull_request_number,
                        "task_id": proposal.task.id,
                        "round": proposal.round,
                        "evidence_sha256": proposal.evidence_sha256,
                        "status": "awaiting_host_approval",
                    },
                )
            self.last_scm_repair_proposal = result
            if isinstance(self.last_scm_observation, dict):
                self.last_scm_observation = {
                    **self.last_scm_observation,
                    "repair_proposal": {
                        "status": result.get("status"),
                        "task_id": result.get("task_id"),
                        "round": result.get("round"),
                        "evidence_sha256": result.get("evidence_sha256"),
                    },
                }
            return result
        except Exception as exc:
            result = {"status": "unavailable", "error_type": type(exc).__name__}
            self.last_scm_repair_proposal = result
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
        self.last_scm_observation = self._observe_scm_pull_request()
        self._propose_scm_ci_repair_task(task_manager)
        qa: dict[str, Any] | None = None
        if integration is None or integration["status"] != "failed":
            qa = self._run_qa_phase(manifest_root, integration)
        security = self._run_security_phase(manifest_root)
        dependency_scan = scan_deliverable_dependencies(manifest_root)
        usage = self._usage_report()
        delivery_task = Task(
            id=self.DELIVERY_TASK_ID,
            title="生成交付文档与交付清单",
            description="汇总项目上下文，撰写标准交付文档集（需求/设计/测试/部署/用户手册）。",
            role="doc_writer",
            status="ready",
        )
        delivery_task.context["requirement_analysis"] = self.last_requirement_analysis or ""
        delivery_task.context["deliverable_dir"] = self.deliverable_dir or ""
        if self.last_scm_observation is not None:
            delivery_task.context["scm_observation"] = dict(self.last_scm_observation)
        delivery_task.context["plan_summary"] = {
            "project": (self.last_plan or {}).get("project", ""),
            "summary": (self.last_plan or {}).get("summary", ""),
        }
        delivery_task.context["task_digest"] = self._task_digest(task_manager)
        ui_ux_spec = self._ui_ux_spec_digest(task_manager)
        if ui_ux_spec is not None:
            delivery_task.context["ui_ux_spec"] = ui_ux_spec
        if integration is not None:
            delivery_task.context["integration_evidence"] = self._integration_evidence_digest(integration)
        if qa is not None:
            delivery_task.context["qa_evidence"] = self._qa_evidence_digest(qa)
        if security is not None:
            delivery_task.context["security_evidence"] = self._security_evidence_digest(security)
        delivery_task.context["dependency_scan"] = dependency_scan
        delivery_task.context["usage_report"] = usage
        knowledge_assets = self._knowledge_prompt(roles=("doc_writer",))
        if knowledge_assets:
            delivery_task.context["knowledge_assets"] = knowledge_assets
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
        acceptance = self._run_acceptance_phase(
            manifest_root,
            project=project,
            integration=(integration or {}).get("suite") if isinstance(integration, dict) else None,
        )
        delivery = {
            "docs_root": docs_root,
            "deliverable_root": str(manifest_root),
            "docs": docs,
            "manifest": None,
            "acceptance": acceptance,
            "integration": integration,
            "qa": qa,
            "security": security,
            "sre": None,
            "release_gate": None,
            "dependency_scan": dependency_scan,
            "build_evidence": None,
            "sbom": None,
            "provenance": None,
            "usage": usage,
            "release": None,
            "monitoring": None,
        }
        self.last_delivery = delivery
        self.last_acceptance = acceptance
        verdict_note = f"，验收 {acceptance['verdict'].upper()}" if acceptance else ""
        release: dict[str, Any] | None = None
        if self.release_requested and (integration is None or integration["status"] != "failed"):
            gate = self._run_release_gate_phase(
                integration=integration,
                qa=qa,
                security=security,
                acceptance=acceptance,
            )
            delivery["release_gate"] = gate
            if gate["status"] == "blocked":
                delivery["release"] = {"status": "blocked", "reason": gate["reason"]}
                self._emit_project_event(
                    "project.release_blocked",
                    payload={"reason": gate.get("blocking_code"), "blockers": gate.get("blockers")},
                )
                print(f"[Release] 发布门禁阻断：{gate['reason']}")
            else:
                release = self._run_release_phase(manifest_root, delivery, project=project)
                delivery["release"] = release
        # Post-delivery monitoring: the deliverable ships with a deterministic
        # health contract and heartbeat guide. Written before the manifest so
        # both are part of the checksummed deliverable set.
        delivery["monitoring"] = self._run_monitoring_phase(
            manifest_root, project=project, release=release
        )
        # Deployment readiness review runs after the monitoring contract so
        # the SRE role can judge the artefacts operations will rely on. The
        # report is written before the manifest and thus ships checksummed.
        delivery["sre"] = self._run_sre_phase(manifest_root, release=release)
        # The manifest is written after the release phase so RELEASE_NOTES.md
        # and release_log.json are part of the checksummed deliverable set.
        # Knowledge extraction runs last so it can record release facts.
        knowledge = self._persist_knowledge(delivery, project=project)
        if knowledge is not None:
            delivery["knowledge"] = knowledge
        build_evidence = build_delivery_evidence(
            project=project,
            integration=integration,
            qa=qa,
            security=security,
            acceptance=acceptance,
            dependency_scan=dependency_scan,
            release=delivery.get("release"),
        )
        build_evidence_record = write_build_evidence(manifest_root, build_evidence)
        sbom_record = write_delivery_sbom(
            manifest_root,
            project=project,
            build_evidence_sha256=build_evidence_record["sha256"],
        )
        delivery["build_evidence"] = build_evidence_record
        delivery["sbom"] = sbom_record
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
        if security is not None:
            payload["security_verdict"] = security.get("verdict")
        if delivery.get("sre") is not None:
            payload["sre_verdict"] = delivery["sre"].get("verdict")
        if delivery.get("release_gate") is not None:
            payload["release_gate_status"] = delivery["release_gate"].get("status")
        if usage is not None:
            payload["llm_calls"] = usage.get("llm_calls")
        if release is not None:
            payload["release_status"] = release.get("status")
        if delivery.get("monitoring") is not None:
            payload["monitoring_status"] = delivery["monitoring"].get("status")
        if delivery.get("knowledge") is not None:
            payload["knowledge"] = {
                key: delivery["knowledge"].get(key)
                for key in ("status", "added", "duplicates", "total")
            }
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
        provenance = write_delivery_provenance(
            bundle["bundle"],
            sbom_path=sbom_record["path"],
            manifest_path=manifest_path,
            build_evidence_path=build_evidence_record["path"],
            lock_path=sbom_record.get("lock_path"),
        )
        delivery["provenance"] = provenance
        delivery["package"]["provenance"] = provenance["path"]
        if release is not None and release.get("status") == "released":
            release["package"] = {"archive": bundle["bundle"], "checksum": bundle["checksum"]}
        delivery["smoke"] = bundle["smoke"]
        print(f"[Delivery] 交付包 {bundle['bundle']} ({bundle['files']} 文件, 冒烟 {bundle['smoke']['status']}){verdict_note}")
        return delivery

    def _run_acceptance_phase(
        self,
        manifest_root: Path,
        *,
        project: str | None,
        integration: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Verify document traceability and executable acceptance evidence."""
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
        traceability = acceptance_verdict(entries, matrix)
        traceability_report = write_acceptance_report(
            docs_dir, entries, matrix, traceability, project=project
        )
        try:
            specs = load_acceptance_test_specs(docs_dir)
            executable = evaluate_executable_acceptance(entries, specs, integration)
        except (OSError, TypeError, ValueError) as exc:
            executable = {
                "verdict": "failed",
                "gaps": [f"acceptance test specification invalid: {type(exc).__name__}: {exc}"],
                "warnings": [],
                "requirements": [],
                "test_count": 0,
                "evidence_started_at": None,
                "evidence_age_seconds": None,
                "evidence_max_age_seconds": 86400,
            }
        executable_report = write_executable_acceptance_report(
            docs_dir, executable, project=project
        )
        if traceability["verdict"] != "passed":
            verdict = "failed"
        elif executable["verdict"] in {"failed", "not_executed", "stale"}:
            verdict = executable["verdict"]
        else:
            verdict = "passed"
        gaps = list(traceability["gaps"]) + list(executable["gaps"])
        warnings = list(traceability["warnings"]) + list(executable["warnings"])
        return {
            "verdict": verdict,
            "gaps": gaps,
            "warnings": warnings,
            "total_requirements": traceability["total_requirements"],
            "test_count": executable["test_count"],
            "traceability_verdict": traceability["verdict"],
            "executable_verdict": executable["verdict"],
            "requirements": executable["requirements"],
            "report": str(traceability_report),
            "executable_report": str(executable_report),
            "evidence_started_at": executable["evidence_started_at"],
            "evidence_age_seconds": executable["evidence_age_seconds"],
        }

    def _run_project_adapter_phase(self, manifest_root: Path) -> dict[str, Any]:
        """Run opt-in language-adapter checks through the authorized tool boundary.

        Adapter execution is opt-in because install steps may access package
        registries and mutate task-local dependency directories. Commands run
        with the deliverable as the active workspace and retain the normal
        developer capability policy, terminal allowlist, timeout and audit.
        """
        if self._env_int("AI_TEAM_PROJECT_ADAPTERS", 0) != 1:
            return {"status": "disabled", "actions": {}, "reason": "set AI_TEAM_PROJECT_ADAPTERS=1 to enable"}

        adapter_name = os.environ.get("AI_TEAM_PROJECT_ADAPTER")
        try:
            detection = DEFAULT_PROJECT_ADAPTER_REGISTRY.resolve(
                manifest_root,
                adapter_name=adapter_name.strip() if adapter_name and adapter_name.strip() else None,
            )
        except LookupError:
            return {"status": "skipped", "actions": {}, "reason": "no supported language adapter detected"}
        except (ValueError, KeyError) as exc:
            return {"status": "unsupported", "actions": {}, "reason": str(exc)}

        service = ToolInvocationService()
        executor = ProjectAdapterExecutor(service)
        actions: dict[str, dict[str, Any]] = {}
        task_id = f"PROJECT-ADAPTER-{self._resolved_project_id() or 'LOCAL'}"
        with workspace_scope(manifest_root):
            for action in ("install", "build", "test", "smoke", "package"):
                plan = DEFAULT_PROJECT_ADAPTER_REGISTRY.plan(
                    manifest_root, action, adapter_name=detection.adapter
                )
                result = executor.execute(
                    plan,
                    role="developer",
                    task_id=task_id,
                    execution_id=f"{task_id}-{action}-{uuid4().hex[:12]}",
                )
                actions[action] = result
                if result.get("status") == "failed":
                    break

        failed_action = next(
            (name for name, result in actions.items() if result.get("status") == "failed"),
            None,
        )
        return {
            "status": "failed" if failed_action else "passed",
            "adapter": detection.adapter,
            "language": detection.language,
            "signals": list(detection.signals),
            "actions": actions,
            "failed_action": failed_action,
            "tool_execution_history": service.history.to_dict(),
        }

    def _run_integration_phase(self, manifest_root: Path) -> dict[str, Any]:
        """Run language-adapter checks, integration tests and static gates.

        Adapter checks are opt-in because dependency installation may access
        package registries. Any adapter command failure or ambiguous project
        toolchain is fail-closed and feeds the bounded developer rework loop.
        """
        timeout = self._env_float("AI_TEAM_INTEGRATION_TIMEOUT", DEFAULT_INTEGRATION_TIMEOUT)
        max_rounds = self._env_int("AI_TEAM_INTEGRATION_MAX_ROUNDS", 2)
        if max_rounds < 0:
            raise ValueError("AI_TEAM_INTEGRATION_MAX_ROUNDS must be >= 0")
        static_enabled = self._env_int("AI_TEAM_STATIC_GATE", 1) == 1
        run_mypy = self._env_int("AI_TEAM_STATIC_MYPY", 0) == 1
        enforce_mypy = self._env_int("AI_TEAM_STATIC_MYPY_ENFORCE", 0) == 1
        static_timeout = self._env_float("AI_TEAM_STATIC_TIMEOUT", DEFAULT_STATIC_TIMEOUT)

        def evaluate() -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
            adapter = self._run_project_adapter_phase(manifest_root)
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
            if adapter.get("status") in {"failed", "unsupported"}:
                suite = dict(suite)
                suite["status"] = "failed"
                suite["adapter_failure"] = adapter
                suite["command"] = suite.get("command") or "project adapter validation"
                suite["output_tail"] = (
                    str(suite.get("output_tail") or "")
                    + "\n[project adapter failure]\n"
                    + str(adapter.get("reason") or adapter.get("failed_action") or adapter.get("status"))
                )[-4000:]
            return suite, static, adapter

        def failed(static: dict[str, Any] | None, suite: dict[str, Any]) -> bool:
            return suite.get("status") == "failed" or (
                static is not None and static.get("status") == "failed"
            )

        suite, static, adapter = evaluate()
        self._emit_project_event(
            "project.integration_started",
            payload={
                "status": suite["status"],
                "test_files": len(suite.get("test_files") or []),
                "static_status": static.get("status") if static is not None else None,
                "adapter_status": adapter.get("status"),
            },
        )
        if not failed(static, suite):
            self._emit_project_event(
                "project.integration_completed",
                payload={
                    "status": suite["status"],
                    "rounds": 0,
                    "summary": suite.get("summary"),
                    "static_status": static.get("status") if static is not None else None,
                    "adapter_status": adapter.get("status"),
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
                "adapter": adapter,
            }

        rework_rounds: list[dict[str, Any]] = []
        for round_no in range(1, max_rounds + 1):
            rework_rounds.append(self._run_rework_round(suite, round_no, static=static))
            suite, static, adapter = evaluate()
            if not failed(static, suite):
                break
        final_status = "failed" if failed(static, suite) else suite["status"]
        payload = {
            "status": final_status,
            "rounds": len(rework_rounds),
            "summary": suite.get("summary"),
            "static_status": static.get("status") if static is not None else None,
            "adapter_status": adapter.get("status"),
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
            "adapter": adapter,
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
        adapter_failure = suite.get("adapter_failure")
        if isinstance(adapter_failure, dict):
            evidence["adapter"] = adapter_failure
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
                "test_cases": [
                    {
                        "selector": item.get("selector"),
                        "status": item.get("status"),
                        "duration_seconds": item.get("duration_seconds"),
                        "summary": item.get("summary"),
                    }
                    for item in (suite.get("test_cases") or [])[:200]
                    if isinstance(item, dict)
                ],
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
        adapter = integration.get("adapter")
        if isinstance(adapter, dict):
            digest["adapter"] = {
                "status": adapter.get("status"),
                "adapter": adapter.get("adapter"),
                "language": adapter.get("language"),
                "failed_action": adapter.get("failed_action"),
                "actions": {
                    name: {
                        "status": result.get("status"),
                        "reason": result.get("reason"),
                    }
                    for name, result in (adapter.get("actions") or {}).items()
                    if isinstance(result, dict)
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

    def _run_security_phase(self, manifest_root: Path) -> dict[str, Any]:
        """Deterministic security audit plus optional security-engineer review.

        The deterministic audit is always computed, so the security gate is
        reproducible without an LLM. A registered security agent triages the
        digest and may *add* a SEC_FAILED verdict, but can never waive a
        deterministic high-severity failure. The report is written before the
        documentation phase so it ships with the deliverable.
        """
        audit = run_security_audit(manifest_root)
        review: dict[str, Any] | None = None
        get_agent = getattr(self.agent_router, "get_agent", None)
        security_agent = get_agent("security") if callable(get_agent) else None
        if security_agent is not None and audit.get("status") == "completed":
            task = Task(
                id="SECURITY-001",
                title="安全审计复核（Security Review）",
                description="复核交付物安全审计证据，给出 SEC_PASSED / SEC_FAILED 结论。",
                role="security",
                status="ready",
            )
            task.context["evidence"] = security_evidence_digest(audit)
            try:
                outcome = security_agent.run(task)
            except Exception as exc:
                review = {"verdict": "UNKNOWN", "summary": f"{type(exc).__name__}: {exc}", "status": "error"}
            else:
                data = getattr(outcome, "data", None)
                record = data.get("security") if isinstance(data, dict) else None
                review = {
                    "verdict": (record or {}).get("verdict") or "UNKNOWN",
                    "summary": (record or {}).get("summary") or "",
                    "status": str(getattr(outcome, "status", "completed")),
                }

        verdict = audit.get("verdict", "SEC_SKIPPED")
        if review is not None and review.get("verdict") == "SEC_FAILED":
            verdict = "SEC_FAILED"
        report_path: Path | None = None
        if audit.get("status") == "completed":
            report_path = write_security_report(manifest_root, audit, review=review)
        security = {
            "status": audit.get("status"),
            "verdict": verdict,
            "files_scanned": audit.get("files_scanned", 0),
            "high_severity": audit.get("high_severity", 0),
            "medium_severity": audit.get("medium_severity", 0),
            "findings": audit.get("findings", []),
            "review": review,
            "report": report_path.relative_to(manifest_root).as_posix() if report_path else None,
        }
        self._emit_project_event(
            "project.security_completed",
            payload={
                "verdict": verdict,
                "high_severity": security["high_severity"],
                "medium_severity": security["medium_severity"],
            },
        )
        print(
            f"[Security] 安全审计结论：{verdict}"
            f"（高危 {security['high_severity']}，中危 {security['medium_severity']}）"
        )
        return security

    @staticmethod
    def _security_evidence_digest(security: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(security, dict):
            return None
        return {
            "verdict": security.get("verdict"),
            "high_severity": security.get("high_severity", 0),
            "medium_severity": security.get("medium_severity", 0),
            "files_scanned": security.get("files_scanned", 0),
            "findings": [
                {
                    "rule": item.get("rule"),
                    "severity": item.get("severity"),
                    "path": item.get("path"),
                    "line": item.get("line"),
                }
                for item in (security.get("findings") or [])[:20]
                if isinstance(item, dict)
            ],
            "report": security.get("report"),
        }

    _RELEASE_BLOCK_REASONS = {
        "integration_failed": "integration regression failed",
        "qa_failed": "QA verdict is QA_FAILED",
        "security_failed": "security audit is SEC_FAILED",
        "release_manager_no_go": "release manager verdict is RELEASE_NO_GO",
        "acceptance_failed": "executable requirement acceptance evidence is not passed",
    }

    def _run_release_gate_phase(
        self,
        *,
        integration: dict[str, Any] | None,
        qa: dict[str, Any] | None,
        security: dict[str, Any] | None,
        acceptance: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Release go/no-go: deterministic blockers first, release manager second."""
        gate = evaluate_release_gate(integration=integration, qa=qa, security=security, acceptance=acceptance)
        record: dict[str, Any] = {
            "status": gate["status"],
            "blockers": gate["blockers"],
            "blocking_code": None,
            "reason": None,
            "manager": None,
        }
        if gate["status"] == "blocked":
            code = gate["blockers"][0]["code"]
            record["blocking_code"] = code
            record["reason"] = self._RELEASE_BLOCK_REASONS.get(code, gate["blockers"][0]["reason"])
            print(f"[ReleaseGate] 发布被确定性门禁阻断：{record['reason']}")
            return record

        get_agent = getattr(self.agent_router, "get_agent", None)
        manager = get_agent("release_manager") if callable(get_agent) else None
        if manager is None:
            return record
        task = Task(
            id="RELEASE-GATE-001",
            title="发布就绪评审（Release Go/No-Go）",
            description="基于集成回归、QA、安全与验收证据给出 RELEASE_GO / RELEASE_NO_GO。",
            role="release_manager",
            status="ready",
        )
        task.context["evidence"] = {
            "integration": (integration or {}).get("status"),
            "qa": (qa or {}).get("verdict"),
            "security": (security or {}).get("verdict"),
            "acceptance": (acceptance or {}).get("verdict"),
        }
        try:
            outcome = manager.run(task)
        except Exception as exc:
            record["manager"] = {
                "verdict": "UNKNOWN",
                "summary": f"{type(exc).__name__}: {exc}",
                "status": "error",
            }
            print(f"[ReleaseGate] 发布经理评审失败（不阻断确定性通过的结果）：{exc}")
            return record
        data = getattr(outcome, "data", None)
        review = data.get("release") if isinstance(data, dict) else None
        record["manager"] = {
            "verdict": (review or {}).get("verdict") or "UNKNOWN",
            "summary": (review or {}).get("summary") or "",
            "status": str(getattr(outcome, "status", "completed")),
        }
        if record["manager"]["verdict"] == "RELEASE_NO_GO":
            record["status"] = "blocked"
            record["blocking_code"] = "release_manager_no_go"
            record["reason"] = self._RELEASE_BLOCK_REASONS["release_manager_no_go"]
        print(f"[ReleaseGate] 发布经理结论：{record['manager']['verdict']}")
        return record

    def _run_sre_phase(
        self, manifest_root: Path, *, release: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Deployment readiness review plus optional SRE-agent triage.

        Runs after the monitoring contract and before the manifest so the
        readiness report ships checksummed. External deployment/APM remains an
        explicit limitation; the verdict only covers evidence in the
        deliverable.
        """
        readiness = run_deployment_readiness(manifest_root, release=release)
        review: dict[str, Any] | None = None
        get_agent = getattr(self.agent_router, "get_agent", None)
        sre_agent = get_agent("sre") if callable(get_agent) else None
        if sre_agent is not None and readiness.get("status") == "completed":
            task = Task(
                id="SRE-001",
                title="部署就绪审查（Deployment Readiness）",
                description="复核部署就绪证据，给出 SRE_READY / SRE_NOT_READY 结论。",
                role="sre",
                status="ready",
            )
            task.context["evidence"] = sre_evidence_digest(readiness)
            try:
                outcome = sre_agent.run(task)
            except Exception as exc:
                review = {"verdict": "UNKNOWN", "summary": f"{type(exc).__name__}: {exc}", "status": "error"}
            else:
                data = getattr(outcome, "data", None)
                record = data.get("sre") if isinstance(data, dict) else None
                review = {
                    "verdict": (record or {}).get("verdict") or "UNKNOWN",
                    "summary": (record or {}).get("summary") or "",
                    "status": str(getattr(outcome, "status", "completed")),
                }

        verdict = readiness.get("verdict", "SRE_SKIPPED")
        if review is not None and review.get("verdict") == "SRE_NOT_READY":
            verdict = "SRE_NOT_READY"
        report_path: Path | None = None
        if readiness.get("status") == "completed":
            report_path = write_sre_report(manifest_root, readiness, review=review)
        sre = {
            "status": readiness.get("status"),
            "verdict": verdict,
            "failed_checks": readiness.get("failed_checks", []),
            "checks": readiness.get("checks", []),
            "review": review,
            "limitation": readiness.get("limitation"),
            "report": report_path.relative_to(manifest_root).as_posix() if report_path else None,
        }
        self._emit_project_event(
            "project.sre_completed",
            payload={"verdict": verdict, "failed_checks": sre["failed_checks"]},
        )
        print(f"[SRE] 部署就绪结论：{verdict}")
        return sre

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

    def _knowledge_prompt(self, *, roles: tuple[str, ...]) -> str:
        """Load role-relevant historical knowledge for a prompt context.

        Returns an empty string when the knowledge base is disabled or has no
        matching asset. A corrupt knowledge file fails closed here, before any
        analysis or delivery work is spent.
        """
        if self.knowledge_base is None:
            return ""
        return build_knowledge_prompt(
            self.knowledge_base,
            roles=roles,
            query=self.knowledge_query,
            limit=DEFAULT_KNOWLEDGE_LIMIT,
        )

    def _persist_knowledge(
        self,
        delivery: dict[str, Any],
        *,
        project: str | None,
    ) -> dict[str, Any] | None:
        """Extract this delivery's lessons into the cross-project knowledge base.

        The knowledge base is a cross-project aid, never part of the delivered
        product: extraction failures are recorded honestly and never invalidate
        the finished delivery.
        """
        if self.knowledge_base is None:
            return None
        try:
            entries = extract_delivery_knowledge(delivery, project=project or "ai-team-delivery")
            counts = KnowledgeBase(self.knowledge_base).add(entries)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._emit_project_event("project.knowledge_failed", payload={"error": error})
            print(f"[Knowledge] 知识资产沉淀失败：{error}")
            return {"status": "failed", "error": error}
        if counts["added"]:
            self._emit_project_event(
                "project.knowledge_extracted",
                payload=counts,
            )
            print(
                f"[Knowledge] 已沉淀 {counts['added']} 条知识资产"
                f"（去重 {counts['duplicates']}，累计 {counts['total']}）"
            )
        return {"status": "completed", **counts}

    def _usage_report(self) -> dict[str, Any] | None:
        """Observed model usage for this run, attributed through the ledger.

        Cost estimation needs configured cost rates; without them the report
        states token/call totals and honestly records the missing estimate.
        """
        if self.usage_ledger is None or not self.usage_project_id:
            return None
        usage = self.usage_ledger.usage_for(self.usage_project_id)
        return {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "llm_calls": usage.llm_calls,
            "cost_usd": None,
        }

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
            "milestone": self.milestone,
            "requirement_entries": requirement_entries,
            "acceptance": delivery.get("acceptance"),
            "integration": integration_summary,
            "qa": {"verdict": (delivery.get("qa") or {}).get("verdict")},
            "usage": delivery.get("usage"),
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

    @staticmethod
    def _ui_ux_spec_digest(task_manager: TaskManager) -> dict[str, Any] | None:
        """Completed UI/UX specification for the DocWriter (None when absent)."""
        for task in task_manager.get_all_tasks():
            if task.role != "ui_ux" or str(task.status) != "completed":
                continue
            payload = task.result
            message = ""
            if isinstance(payload, dict):
                message = str(payload.get("message") or payload.get("summary") or "")
            elif payload is not None:
                message = str(payload)
            if not message.strip():
                continue
            project_type = task.context.get("project_type")
            return {
                "task_id": task.id,
                "project_type": project_type if isinstance(project_type, str) else "",
                "spec": message[:6000],
            }
        return None

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

    def _run_monitoring_phase(
        self,
        manifest_root: Path,
        *,
        project: str | None,
        release: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Attach the post-delivery monitoring contract to the deliverable.

        The contract only records what the heartbeat can verify offline (release
        anchor, manifest integrity, regression suite); no cloud APM is claimed.
        A monitoring write failure never invalidates the product.
        """
        try:
            outcome = write_monitoring_contract(
                manifest_root,
                project=project or "ai-team-delivery",
                release=release,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._emit_project_event("project.monitoring_failed", payload={"error": error})
            print(f"[Monitoring] 监控契约写入失败：{error}")
            return {"status": "failed", "error": error}
        self._emit_project_event(
            "project.monitoring_configured",
            payload={"contract": outcome.get("contract"), "probes": outcome.get("probes")},
        )
        print(
            f"[Monitoring] 已写入监控契约 {outcome.get('contract')}"
            f"（探针：{', '.join(outcome.get('probes') or [])}）"
        )
        return outcome

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

    def revise_persisted(
        self,
        project_id: str,
        adapter: ProjectPersistenceAdapter,
        requirement: str,
        *,
        event_persistence: WorkflowEventPersistenceAdapter | None = None,
    ) -> tuple[ProjectResult, dict[str, Any]]:
        """Re-plan a persisted project after a change request (T14).

        The analyst receives the change request as an authoritative revision,
        the planner produces a new task graph, and a deterministic impact
        analysis decides which tasks must run again: unaffected completed
        tasks keep their state and evidence, while changed tasks and their
        downstream are reset. Only those tasks are executed; the delivery
        phase (integration regression, QA, documents, packaging) runs again
        as the gate for the revised product.
        """
        if not isinstance(adapter, ProjectPersistenceAdapter):
            raise TypeError("adapter must be a ProjectPersistenceAdapter")
        if not isinstance(requirement, str):
            raise TypeError("requirement must be a string")
        if not requirement.strip():
            raise ValueError("requirement cannot be empty")
        change_request = self.change_request
        if not isinstance(change_request, str) or not change_request.strip():
            raise ValueError(
                "a non-empty change request is required to revise a persisted project"
            )

        snapshot = adapter.load(project_id)
        self._restore_tool_execution_history(snapshot.task_manager, snapshot.tool_execution_history)
        self._rehydrate_workflow_event_log(project_id, event_persistence)
        self._emit_project_event(
            "project.change_request_received",
            payload={
                "source": "persistence",
                "project_id": project_id,
                "chars": len(change_request),
            },
        )

        plan = self.create_plan(requirement)
        planned_manager = self.build_task_manager(plan)
        revision = build_incremental_revision(
            snapshot.task_manager, planned_manager.get_all_tasks()
        )
        merged_manager = TaskManager(list(revision.tasks))
        self.last_plan = plan
        self.last_task_manager = merged_manager
        self.last_revision = {**revision.to_dict(), "project_id": project_id, "chars": len(change_request)}
        self._emit_project_event(
            "project.incremental_revision_planned", payload=self.last_revision
        )
        print(
            f"[Revision] 变更影响分析（{revision.mode}）：复用 {len(revision.reused_task_ids)} 个"
            f"已完成任务，重执行 {len(revision.affected_task_ids)} 个，"
            f"新增 {len(revision.added_task_ids)} 个，移除 {len(revision.removed_task_ids)} 个"
        )
        if revision.removed_completed_task_ids:
            print(
                "[Revision] 变更删除的已完成任务不再纳入任务图："
                + ", ".join(revision.removed_completed_task_ids)
            )

        project_name = plan.get("project")

        def persist_boundary(manager: TaskManager) -> None:
            boundary_result = ProjectResult.from_task_manager(manager, project=project_name)
            adapter.update(
                project_id, plan=plan, task_manager=manager, result=boundary_result
            )

        result = self.execute(merged_manager, state_change_hook=persist_boundary)
        adapter.update(
            project_id,
            plan=plan,
            task_manager=self.last_task_manager,
            result=result,
        )
        return result, dict(self.last_revision)

    def run(self, requirement: str) -> ProjectResult:
        plan = self.create_plan(requirement)
        task_manager = self.build_task_manager(plan)
        return self.execute(task_manager)
