"""Requirement changes prepared against a quiescent, persisted task graph."""
from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from agents.analyst import run_quality_checked_analysis
from runtime.failure_classification import FailureClass
from runtime.failure_recovery_executor import RecoveryIntent
from runtime.failure_recovery_policy import RecoveryAction
from runtime.project_persistence import ProjectSnapshot
from runtime.recovery_replan_coordinator import RecoveryReplanCoordinator
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.task_validator import TASK_REQUIRED_FIELDS, validate_plan


@dataclass(frozen=True)
class ChangeProposal:
    plan: dict[str, Any]
    task_manager: TaskManager
    analysis: str
    record: dict[str, Any]


def _definition(task: Task) -> dict[str, Any]:
    return {key: deepcopy(getattr(task, key)) for key in sorted(TASK_REQUIRED_FIELDS)}


def prepare_change(
    snapshot: ProjectSnapshot,
    *,
    requirement: str,
    change: str,
    analyst: Any,
    planner: Callable[[str, str], dict[str, Any]],
) -> ChangeProposal:
    """Validate and materialize a candidate without changing the source snapshot.

    Completed task definitions are immutable. Rework must have a fresh ID;
    otherwise preserved completion state would incorrectly satisfy new work.
    """
    for name, value in (("requirement", requirement), ("change", change)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    if snapshot.plan is None:
        raise ValueError("a saved project plan is required")
    source_plan = snapshot.plan
    validate_plan(source_plan)
    if any(snapshot.task_manager.is_active(task.id) for task in snapshot.task_manager.get_all_tasks()):
        raise RuntimeError("Cannot apply change while tasks are active")
    if analyst is None:
        raise ValueError("No analyst agent is registered")
    previous = {task.id: task for task in snapshot.task_manager.get_all_tasks()}
    definitions = {task_id: _definition(task) for task_id, task in previous.items()}
    baseline = {
        "original_requirement": requirement,
        "project": source_plan["project"],
        "summary": source_plan["summary"],
        "tasks": [dict(definitions[task.id], status=task.status) for task in previous.values()],
    }
    analysis_request = (
        "分析以下项目的客户需求变更。输出更新后的完整需求规格，并明确影响的功能、"
        "任务、依赖、验收标准和回归测试；不要把已完成任务当作新需求已实现的证据。\n"
        + json.dumps(baseline, ensure_ascii=False)
    )
    analysis = run_quality_checked_analysis(analyst, requirement=analysis_request, clarifications=change)
    if analysis.status != "completed" or not analysis.data.get("quality", {}).get("ok"):
        raise ValueError("change analysis did not pass the specification quality check")
    prompt = (
        "为客户变更生成完整的替换任务图（不是只有新增任务）。保持 project 名称不变。"
        "所有 completed 任务必须原样保留 ID、标题、描述、角色及依赖；"
        "对已完成工作的修改必须新增任务 ID，并加入实现、测试和回归工作。"
        "不受影响的任务原样保留；需要替换的未完成任务可移除。\n"
        + json.dumps({"baseline": baseline, "customer_change": change}, ensure_ascii=False)
    )

    def validated_planner(_: str) -> dict[str, Any]:
        plan = deepcopy(planner(prompt, analysis.message))
        validate_plan(plan)
        if plan["project"] != source_plan["project"]:
            raise ValueError("change cannot rename the project")
        candidate = {item["id"]: item for item in plan["tasks"]}
        for task_id, task in previous.items():
            if task.status == "completed" and candidate.get(task_id) != definitions[task_id]:
                raise ValueError(f"completed task {task_id} must remain unchanged; use a new task ID for rework")
        if not any(item["id"] not in previous or previous[item["id"]].status != "completed" for item in plan["tasks"]):
            raise ValueError("change plan must contain unfinished work")
        return plan

    # Work on a detached manager: commit never touches the caller's live graph.
    manager = TaskManager([Task.from_dict(task.to_dict()) for task in previous.values()])
    coordinator = RecoveryReplanCoordinator(manager, validated_planner)
    intent = RecoveryIntent(
        action=RecoveryAction.REPLAN, task_id="CHANGE-REQUEST",
        failure_class=FailureClass.SPECIFICATION, failure_reason=change,
        decision_reason="customer requirement change", attempt=0,
    )
    outcome = coordinator.prepare(intent, prompt)
    coordinator.commit(outcome)
    candidate = {item["id"]: item for item in outcome.result.plan["tasks"]}
    unchanged = sorted(task_id for task_id in previous if candidate.get(task_id) == definitions[task_id])
    # The recovery materializer resets unfinished work. Unaffected tasks must
    # instead retain their evidence and status in a customer-change operation.
    manager.replace_task_graph([
        Task.from_dict(previous[task.id].to_dict()) if task.id in unchanged else task
        for task in manager.get_all_tasks()
    ])
    record = {
        "status": "accepted", "change": change,
        "added_tasks": sorted(set(candidate) - set(previous)),
        "modified_tasks": sorted(task_id for task_id in set(candidate) & set(previous) if task_id not in unchanged),
        "superseded_tasks": sorted(set(previous) - set(candidate)),
        "preserved_tasks": unchanged,
        "analysis": analysis.message,
    }
    return ChangeProposal(outcome.result.plan, manager, analysis.message, record)
