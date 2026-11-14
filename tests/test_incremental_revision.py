"""Incremental re-execution contracts for persisted projects (TaskPlan T14)."""

from __future__ import annotations

import json

import pytest

from agents.analyst import RequirementAnalystAgent
from core.project_orchestrator import ProjectOrchestrator
from core.project_result import ProjectResult
from runtime.agent_config import AgentConfig
from runtime.change_impact import build_incremental_revision, normalize_task_text
from runtime.llm.base import BaseLLM
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.task import Task
from runtime.task_manager import TaskManager

ANALYSIS_MARKDOWN = """# 需求规格说明（草案）

## 一、项目概述
词频统计工具，支持导出 CSV。

## 二、功能需求清单
### REQ-001 词频统计（必须）
统计单词出现次数。
验收标准：输出与样例一致。

## 三、非功能需求
-【假设】UTF-8 输入。

## 四、验收标准
见 REQ-001。

## 五、假设与约束
-【假设】单机运行。

## 六、待确认问题
无。
"""

CHANGE_REQUEST = "CHG-001：新增导出 CSV 功能。\n"


class _CapturingLLM(BaseLLM):
    def __init__(self, text: str):
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        self.prompts.append(prompt)
        return self.text

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        raise AssertionError("not used")


class _StubPlanner:
    role = "planner"

    def __init__(self, plans: list[dict]):
        self.plans = list(plans)
        self.requests: list[str] = []

    def run(self, task: Task) -> dict:
        self.requests.append(task.description)
        plan = self.plans.pop(0) if len(self.plans) > 1 else self.plans[0]
        return {"plan": plan}


class _StubRouter:
    def __init__(self, analyst, planner):
        self.agents = {"analyst": analyst, "planner": planner}

    def get_agent(self, role):
        return self.agents.get(role)


class RecorderFactory:
    """Mimics the orchestrator seam: execute pending/ready tasks only."""

    executed: list[str] = []
    failing: set[str] = set()

    def __init__(self, task_manager: TaskManager, agent_router: object):
        self.task_manager = task_manager

    def run(self) -> None:
        for task in self.task_manager.get_all_tasks():
            if task.status == "pending" and all(
                self.task_manager.get_task(dependency).status == "completed"
                for dependency in task.dependencies
            ):
                self.task_manager.mark_ready(task.id)
        for task in self.task_manager.get_all_tasks():
            if task.status != "ready":
                continue
            self.__class__.executed.append(task.id)
            self.task_manager.mark_running(task.id)
            if task.id in self.__class__.failing:
                self.task_manager.mark_failed(task.id, "execution failed during revision")
                continue
            self.task_manager.mark_completed(
                task.id, {"status": "completed", "message": "executed during revision"}
            )


def _factory(task_manager: TaskManager, agent_router: object) -> RecorderFactory:
    return RecorderFactory(task_manager, agent_router)


def _task(task_id, title, role="developer", status="pending", dependencies=(), **context) -> Task:
    task = Task(
        id=task_id,
        title=title,
        description=f"{title} 的实现说明",
        role=role,
        status=status,
        dependencies=list(dependencies),
    )
    task.context.update(context)
    return task


def _plan(project: str, tasks: list[dict]) -> dict:
    return {"project": project, "summary": "词频统计工具", "tasks": tasks}


def _plan_entry(task_id, title, role="developer", dependencies=()) -> dict:
    return {
        "id": task_id,
        "title": title,
        "description": f"{title} 的实现说明",
        "role": role,
        "dependencies": list(dependencies),
    }


def _completed(task_id, title, role="developer", dependencies=(), message=None) -> Task:
    task = _task(task_id, title, role=role, status="completed", dependencies=dependencies)
    task.result = {"status": "completed", "message": message or f"{title} baseline"}
    task.test_result = {"passed": True}
    return task


# ---------------------------------------------------------------------------
# Deterministic impact analysis
# ---------------------------------------------------------------------------


def test_normalize_task_text_is_stable_across_case_and_punctuation():
    assert normalize_task_text("实现 WordCount.py。") == normalize_task_text(" 实现 wordcount py ")
    assert normalize_task_text("实现 WordCount.py。") != normalize_task_text("实现 CSV 导出")


def test_unchanged_graph_reuses_completed_evidence():
    old = TaskManager([
        _completed("ARCH-001", "架构设计", role="architect"),
        _completed("DEV-001", "词频统计", dependencies=["ARCH-001"]),
    ])
    new = [
        _task("ARCH-001", "架构设计", role="architect"),
        _task("DEV-001", "词频统计", dependencies=["ARCH-001"]),
    ]

    revision = build_incremental_revision(old, new)

    assert revision.mode == "incremental"
    assert revision.reused_task_ids == ("ARCH-001", "DEV-001")
    assert revision.affected_task_ids == ()
    merged = {task.id: task for task in revision.tasks}
    assert merged["DEV-001"].status == "completed"
    assert merged["DEV-001"].result["message"] == "词频统计 baseline"
    assert merged["DEV-001"].test_result == {"passed": True}
    assert merged["DEV-001"].status_history[-1]["incremental_reuse"] is True
    assert merged["DEV-001"].context["incremental_revision"] == "reused"


def test_changed_task_and_downstream_are_reexecuted():
    old = TaskManager([
        _completed("ARCH-001", "架构设计", role="architect"),
        _completed("DEV-001", "词频统计", dependencies=["ARCH-001"]),
        _completed("TEST-001", "词频测试", role="tester", dependencies=["DEV-001"]),
        _completed("DEV-002", "帮助信息"),
    ])
    new = [
        _task("ARCH-001", "架构设计", role="architect"),
        _task("DEV-001", "词频统计与 CSV 导出", dependencies=["ARCH-001"]),
        _task("TEST-001", "词频测试", role="tester", dependencies=["DEV-001"]),
        _task("DEV-002", "帮助信息"),
    ]

    revision = build_incremental_revision(old, new)

    assert revision.reused_task_ids == ("ARCH-001", "DEV-002")
    assert revision.affected_task_ids == ("DEV-001", "TEST-001")
    assert revision.reset_completed_task_ids == ("DEV-001", "TEST-001")
    merged = {task.id: task for task in revision.tasks}
    assert merged["DEV-001"].status == "pending"
    assert merged["TEST-001"].status == "pending"
    assert merged["ARCH-001"].result["message"] == "架构设计 baseline"


def test_new_task_keeps_unrelated_branch_evidence():
    old = TaskManager([
        _completed("DEV-001", "词频统计"),
        _completed("DEV-002", "帮助信息"),
    ])
    new = [
        _task("DEV-001", "词频统计"),
        _task("DEV-002", "帮助信息"),
        _task("DEV-003", "CSV 导出"),
    ]

    revision = build_incremental_revision(old, new)

    assert revision.reused_task_ids == ("DEV-001", "DEV-002")
    assert revision.added_task_ids == ("DEV-003",)
    assert revision.affected_task_ids == ("DEV-003",)
    assert revision.mode == "incremental"


def test_removed_completed_task_is_reported_and_dropped():
    old = TaskManager([
        _completed("DEV-001", "词频统计"),
        _completed("DEV-002", "已删除的大小写归一化"),
    ])
    new = [_task("DEV-001", "词频统计")]

    revision = build_incremental_revision(old, new)

    assert revision.reused_task_ids == ("DEV-001",)
    assert revision.removed_task_ids == ("DEV-002",)
    assert revision.removed_completed_task_ids == ("DEV-002",)
    assert [task.id for task in revision.tasks] == ["DEV-001"]


def test_unmatched_regenerated_graph_falls_back_to_full_rerun():
    old = TaskManager([_completed("DEV-001", "实现词频统计")])
    new = [_task("TASK-009", "设计数据库表结构", role="architect")]

    revision = build_incremental_revision(old, new)

    assert revision.mode == "full"
    assert revision.reused_task_ids == ()
    assert revision.affected_task_ids == ("TASK-009",)
    assert revision.removed_completed_task_ids == ("DEV-001",)
    merged = revision.tasks[0]
    assert merged.status == "pending"
    assert merged.context["incremental_revision"] == "new"


def test_renamed_ids_with_identical_text_preserve_evidence():
    old = TaskManager([
        _completed("TASK-001", "架构设计", role="architect"),
        _completed("TASK-002", "词频统计", dependencies=["TASK-001"]),
    ])
    new = [
        _task("PLAN-001", "架构设计", role="architect"),
        _task("PLAN-002", "词频统计", dependencies=["PLAN-001"]),
    ]

    revision = build_incremental_revision(old, new)

    assert revision.match_bases == {"title": 2}
    assert revision.reused_task_ids == ("PLAN-001", "PLAN-002")
    assert [task.dependencies for task in revision.tasks] == [[], ["PLAN-001"]]


def test_stale_non_terminal_status_is_normalized_to_pending():
    stale = _task("DEV-001", "词频统计", status="running")
    old = TaskManager([stale])
    new = [_task("DEV-001", "词频统计")]

    revision = build_incremental_revision(old, new)

    merged = revision.tasks[0]
    assert revision.carried_task_ids == ("DEV-001",)
    assert merged.status == "pending"
    assert merged.status_history[-1]["reason"].startswith("增量续跑")


def test_impact_analysis_is_deterministic():
    old = TaskManager([
        _completed("ARCH-001", "架构设计", role="architect"),
        _completed("DEV-001", "词频统计", dependencies=["ARCH-001"]),
    ])
    first = build_incremental_revision(old, [
        _task("ARCH-001", "架构设计", role="architect"),
        _task("DEV-001", "词频统计", dependencies=["ARCH-001"]),
    ])
    second = build_incremental_revision(old, [
        _task("ARCH-001", "架构设计", role="architect"),
        _task("DEV-001", "词频统计", dependencies=["ARCH-001"]),
    ])

    assert first.to_dict() == second.to_dict()


# ---------------------------------------------------------------------------
# Orchestrator-level revision
# ---------------------------------------------------------------------------


def _write_snapshot(adapter: ProjectPersistenceAdapter, manager: TaskManager, plan: dict):
    adapter.save(
        "PROJECT-001",
        plan=plan,
        task_manager=manager,
        result=ProjectResult.from_task_manager(manager, project=plan["project"]),
    )


def _baseline():
    plan = _plan("wordcount", [
        _plan_entry("ARCH-001", "架构设计", role="architect"),
        _plan_entry("DEV-001", "词频统计", dependencies=["ARCH-001"]),
    ])
    manager = TaskManager([
        _completed("ARCH-001", "架构设计", role="architect"),
        _completed("DEV-001", "词频统计", dependencies=["ARCH-001"]),
    ])
    return plan, manager


def _revised_plan(description_title: str = "词频统计与 CSV 导出") -> dict:
    return _plan("wordcount", [
        _plan_entry("ARCH-001", "架构设计", role="architect"),
        _plan_entry("DEV-001", description_title, dependencies=["ARCH-001"]),
    ])


def _project(plans: list[dict], change_request: str | None = CHANGE_REQUEST) -> ProjectOrchestrator:
    llm = _CapturingLLM(ANALYSIS_MARKDOWN)
    router = _StubRouter(
        RequirementAnalystAgent(AgentConfig(role="analyst", model=""), llm=llm),
        _StubPlanner(plans),
    )
    return ProjectOrchestrator(
        agent_router=router,
        orchestrator_factory=_factory,
        change_request=change_request,
    )


def test_revise_persisted_executes_only_affected_tasks(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    plan, manager = _baseline()
    _write_snapshot(adapter, manager, plan)
    RecorderFactory.executed = []
    RecorderFactory.failing = set()
    project = _project([_revised_plan()])

    result, revision = project.revise_persisted("PROJECT-001", adapter, "统计文本词频并导出 CSV")

    assert RecorderFactory.executed == ["DEV-001"]
    assert revision["mode"] == "incremental"
    assert revision["reused"] == ["ARCH-001"]
    assert revision["affected"] == ["DEV-001"]

    restored = adapter.load("PROJECT-001")
    assert restored.plan == project.last_plan
    assert restored.result == result
    assert restored.task_manager.get_task("ARCH-001").status == "completed"
    assert restored.task_manager.get_task("DEV-001").status == "completed"
    assert restored.task_manager.get_task("ARCH-001").result["message"] == "架构设计 baseline"
    assert (
        restored.task_manager.get_task("DEV-001").result["message"]
        == "executed during revision"
    )
    assert result.success is True

    analyst = project.agent_router.get_agent("analyst")
    assert 'source="customer.change_request"' in analyst.llm.prompts[0]
    assert "CHG-001" in analyst.llm.prompts[0]


def test_revise_persisted_falls_back_to_full_rerun_when_graph_unmatched(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    plan, manager = _baseline()
    _write_snapshot(adapter, manager, plan)
    RecorderFactory.executed = []
    RecorderFactory.failing = set()
    regenerated = _plan("wordcount", [
        _plan_entry("TASK-009", "设计数据库表结构", role="architect"),
    ])
    project = _project([regenerated])

    result, revision = project.revise_persisted("PROJECT-001", adapter, "统计文本词频")

    assert revision["mode"] == "full"
    assert revision["reused"] == []
    assert revision["removed_completed"] == ["ARCH-001", "DEV-001"]
    assert RecorderFactory.executed == ["TASK-009"]
    assert result.success is True
    restored = adapter.load("PROJECT-001")
    assert [task.id for task in restored.task_manager.get_all_tasks()] == ["TASK-009"]


def test_revise_persisted_reports_affected_failure_honestly(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    plan, manager = _baseline()
    _write_snapshot(adapter, manager, plan)
    RecorderFactory.executed = []
    RecorderFactory.failing = {"DEV-001"}
    project = _project([_revised_plan()])

    try:
        result, revision = project.revise_persisted("PROJECT-001", adapter, "统计文本词频")
    finally:
        RecorderFactory.failing = set()

    assert result.success is False
    assert result.status == "failed"
    assert result.failed_tasks == ("DEV-001",)
    assert revision["affected"] == ["DEV-001"]
    restored = adapter.load("PROJECT-001")
    assert restored.result == result
    assert restored.task_manager.get_task("ARCH-001").status == "completed"
    assert restored.task_manager.get_task("DEV-001").status == "failed"


def test_revise_persisted_requires_a_change_request(tmp_path):
    adapter = ProjectPersistenceAdapter(tmp_path)
    plan, manager = _baseline()
    _write_snapshot(adapter, manager, plan)
    project = _project([_revised_plan()], change_request=None)

    with pytest.raises(ValueError, match="change request"):
        project.revise_persisted("PROJECT-001", adapter, "统计文本词频")


def test_revise_persisted_requires_an_existing_project(tmp_path):
    project = _project([_revised_plan()])

    with pytest.raises(KeyError):
        project.revise_persisted("MISSING", ProjectPersistenceAdapter(tmp_path), "统计文本词频")


def test_revise_persisted_rejects_non_adapter(tmp_path):
    project = _project([_revised_plan()])

    with pytest.raises(TypeError):
        project.revise_persisted("PROJECT-001", object(), "统计文本词频")


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def test_run_project_revision_requires_existing_snapshot():
    import main as main_module

    with pytest.raises(ValueError, match="persisted project snapshot not found"):
        main_module.run_project_revision(
            "统计文本词频", project_path="missing/PROJECT-001.json", change_request="CHG-001: 导出"
        )


def test_run_project_revision_requires_change_request():
    import main as main_module

    with pytest.raises(ValueError, match="change request"):
        main_module.run_project_revision(
            "统计文本词频", project_path="PROJECT-001.json", change_request="  "
        )


def test_main_requires_change_request_for_revise_project(monkeypatch, tmp_path):
    import main as main_module

    snapshot = tmp_path / "PROJECT-001.json"
    snapshot.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(main_module.sys, "argv", [
        "main.py", "统计文本词频", "--revise-project", str(snapshot),
    ])

    with pytest.raises(SystemExit):
        main_module.main()


def test_main_prints_revision_report_in_json(monkeypatch, capsys, tmp_path):
    import main as main_module

    snapshot = tmp_path / "PROJECT-001.json"
    snapshot.write_text("{}", encoding="utf-8")
    change = tmp_path / "change.md"
    change.write_text("CHG-001: 导出 CSV\n", encoding="utf-8")

    class FakeTaskManager:
        def get_all_tasks(self):
            return [_task("DEV-001", "词频统计", status="completed")]

    class FakeResult:
        success = True
        status = "completed"
        total_tasks = 1
        completed_tasks = 1

        def to_dict(self):
            return {"success": True, "status": "completed"}

    revision = {
        "mode": "incremental",
        "reused": ["ARCH-001"],
        "affected": ["DEV-001"],
        "added": [],
        "carried": [],
        "removed": [],
        "removed_completed": [],
        "reset_completed": ["DEV-001"],
        "match_bases": {"id": 2},
        "project_id": "PROJECT-001",
        "chars": 13,
    }

    monkeypatch.setattr(
        main_module,
        "run_project_revision",
        lambda requirement, **kwargs: (FakeTaskManager(), FakeResult(), revision),
    )
    monkeypatch.setattr(main_module.sys, "argv", [
        "main.py", "统计文本词频",
        "--revise-project", str(snapshot),
        "--change-request", str(change),
        "--output", "json",
    ])

    assert main_module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["revision"] == revision
    assert payload["tasks"][0]["id"] == "DEV-001"
