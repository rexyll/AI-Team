"""T12: project-type gated UI/UX role and developer specialist matching."""

from __future__ import annotations

from copy import deepcopy

import pytest

from agents.developer import DeveloperAgent
from agents.ui_ux import UIDesignerAgent
from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_config import AgentConfig
from runtime.llm.base import BaseLLM
from runtime.project_type import (
    SPECIALIST_LABELS,
    apply_project_profile,
    classify_task_specialist,
    detect_project_profile,
    specialist_prompt,
)
from runtime.task import Task
from runtime.task_validator import validate_plan
from security.runtime_capability import DEFAULT_RUNTIME_CAPABILITY_POLICY


class _FixedLLM(BaseLLM):
    def __init__(self, text: str):
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        self.prompts.append(prompt)
        return self.text

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        raise AssertionError("ui_ux / prompt-only tests must not use tools")


def _web_plan() -> dict:
    return {
        "project": "todo-web",
        "summary": "待办事项 Web 应用",
        "tasks": [
            {
                "id": "ARCH-001",
                "title": "架构设计",
                "description": "设计前后端模块",
                "role": "architect",
                "dependencies": [],
            },
            {
                "id": "DEV-001",
                "title": "实现任务管理页面",
                "description": "实现前端页面与交互",
                "role": "developer",
                "dependencies": ["ARCH-001"],
            },
            {
                "id": "DEV-002",
                "title": "实现后端接口",
                "description": "提供任务 CRUD 接口与持久化",
                "role": "developer",
                "dependencies": ["ARCH-001"],
            },
        ],
    }


def _cli_plan() -> dict:
    return {
        "project": "todo-cli",
        "summary": "待办事项命令行工具",
        "tasks": [
            {
                "id": "DEV-001",
                "title": "实现 todo 命令行入口",
                "description": "支持 add/list/done 子命令",
                "role": "developer",
                "dependencies": [],
            },
        ],
    }


class _StubPlanner:
    def __init__(self, plan: dict):
        self.plan = plan

    def run(self, task):
        return {"plan": deepcopy(self.plan)}


class _UiUxRouter:
    """Minimal router exposing only the agents used by create_plan()."""

    def __init__(self, plan: dict, *, with_ui_ux: bool = True):
        self.agents = {"planner": _StubPlanner(plan)}
        if with_ui_ux:
            self.agents["ui_ux"] = UIDesignerAgent(
                AgentConfig(role="ui_ux", model=""), llm=_FixedLLM("# UX")
            )

    def get_agent(self, role):
        return self.agents.get(role)

    def has_agent(self, role):
        return role in self.agents


def test_web_requirement_enables_ui_ux_and_frontend_backend():
    profile = detect_project_profile("开发一个待办事项 Web 应用，包含登录页面和任务列表界面")

    assert profile.project_type == "web"
    assert profile.ui_required is True
    assert profile.specialists == ("ui_ux", "frontend", "backend")
    assert any(signal.startswith("web:") for signal in profile.signals)
    assert any(signal.startswith("ui:") for signal in profile.signals)


def test_cli_requirement_does_not_enable_ui_ux():
    profile = detect_project_profile("开发一个命令行 todo 工具，支持 add/list/done 子命令")

    assert profile.project_type == "cli"
    assert profile.ui_required is False
    assert profile.specialists == ("cli",)


def test_api_requirement_enables_backend_specialist_only():
    profile = detect_project_profile("开发一个任务管理 REST API 服务，提供增删改查接口")

    assert profile.project_type == "api"
    assert profile.ui_required is False
    assert profile.specialists == ("backend",)


def test_interface_signal_enables_ui_ux_for_unclassified_project():
    profile = detect_project_profile("实现学生管理系统的界面和表单交互")

    assert profile.project_type == "general"
    assert profile.ui_required is True
    assert profile.specialists == ("ui_ux",)


def test_empty_requirement_is_general_without_specialists():
    profile = detect_project_profile("")

    assert profile.project_type == "general"
    assert profile.ui_required is False
    assert profile.specialists == ()
    assert profile.signals == ()


def test_ui_ux_task_is_injected_before_interface_developer_work():
    plan = _web_plan()
    original = deepcopy(plan)
    profile = detect_project_profile("开发一个待办事项 Web 应用，包含任务列表页面")

    augmented = apply_project_profile(plan, profile, ui_ux_enabled=True)
    validate_plan(augmented)

    assert augmented is not plan
    assert plan == original
    ux_tasks = [task for task in augmented["tasks"] if task["role"] == "ui_ux"]
    assert len(ux_tasks) == 1
    ux_task = ux_tasks[0]
    assert ux_task["id"] == "UX-001"
    assert ux_task["dependencies"] == ["ARCH-001"]

    by_id = {task["id"]: task for task in augmented["tasks"]}
    assert "UX-001" in by_id["DEV-001"]["dependencies"]
    # Backend work does not depend on the interface design.
    assert "UX-001" not in by_id["DEV-002"]["dependencies"]


def test_profile_without_interface_leaves_plan_untouched():
    plan = _web_plan()
    profile = detect_project_profile("开发一个命令行 todo 工具")

    assert apply_project_profile(plan, profile, ui_ux_enabled=True) is plan


def test_unavailable_ui_ux_agent_downgrades_injected_role():
    plan = _web_plan()
    plan["tasks"].append(
        {
            "id": "UX-001",
            "title": "UI/UX 设计规范",
            "description": "页面与交互设计",
            "role": "ui_ux",
            "dependencies": ["ARCH-001"],
        }
    )
    profile = detect_project_profile("开发一个待办事项 Web 应用，包含任务列表页面")

    downgraded = apply_project_profile(plan, profile, ui_ux_enabled=False)
    validate_plan(downgraded)

    assert [task["role"] for task in downgraded["tasks"]].count("ui_ux") == 0
    assert downgraded["tasks"][-1]["role"] == "architect"


def test_developer_task_specialist_matching_uses_enabled_roles_only():
    profile = detect_project_profile("开发一个待办事项 Web 应用，包含任务列表页面")

    assert classify_task_specialist(
        title="实现任务管理页面", description="实现前端页面与交互", profile=profile
    ) == "frontend"
    assert classify_task_specialist(
        title="实现后端接口", description="提供任务 CRUD 接口与持久化", profile=profile
    ) == "backend"
    assert classify_task_specialist(
        title="重构工具函数", description="整理内部工具函数", profile=profile
    ) is None
    assert classify_task_specialist(
        title="实现任务管理页面", description="前端页面", profile=None
    ) is None


def test_data_specialist_only_for_data_projects():
    data_profile = detect_project_profile("构建一个 ETL 数据管道与报表平台")
    web_profile = detect_project_profile("开发一个待办事项 Web 应用，包含任务列表页面")

    assert classify_task_specialist(
        title="实现数据清洗管道", description="解析源数据并计算统计指标", profile=data_profile
    ) == "data"
    # A web project never assigns the data specialist even when keywords match.
    assert classify_task_specialist(
        title="实现数据清洗管道", description="解析源数据并计算统计指标", profile=web_profile
    ) is None


def test_specialist_prompts_are_focus_blocks_not_unknown_roles():
    assert "前端工程师" in SPECIALIST_LABELS["frontend"]
    assert "前端" in specialist_prompt("frontend")
    assert specialist_prompt(None) == ""
    assert specialist_prompt("unknown-specialist") == ""


def test_developer_prompt_includes_specialist_focus_block():
    agent = DeveloperAgent(AgentConfig(role="developer", model=""), llm=_FixedLLM("done"))
    task = Task(
        id="DEV-001",
        title="实现后端接口",
        description="提供任务接口",
        role="developer",
        context={"developer_specialist": "backend"},
    )

    messages = agent._build_messages(agent.build_context(task))

    assert "SPECIALIST FOCUS（后端工程师）" in messages[1]["content"]
    assert "后端工程师" in messages[1]["content"]


def test_ui_designer_agent_produces_spec_with_project_type():
    llm = _FixedLLM("# UI/UX 设计规范\n\n- 任务列表页")
    agent = UIDesignerAgent(AgentConfig(role="ui_ux", model=""), llm=llm)
    task = Task(
        id="UX-001",
        title="UI/UX 设计规范",
        description="设计任务列表页面",
        role="ui_ux",
        context={"project_type": "web"},
    )

    result = agent.run(task)

    assert result.status == "completed"
    assert result.agent == "ui_ux"
    assert result.data["ui_ux"]["project_type"] == "web"
    assert "任务列表页" in result.data["ui_ux"]["spec"]
    assert "web" in llm.prompts[0]


def test_ui_ux_role_has_no_tool_capability():
    assert DEFAULT_RUNTIME_CAPABILITY_POLICY.allows("ui_ux", "read_file") is False
    assert DEFAULT_RUNTIME_CAPABILITY_POLICY.allows("ui_ux", "run_command") is False


def test_create_plan_enables_profile_and_build_task_manager_records_contexts():
    project = ProjectOrchestrator(agent_router=_UiUxRouter(_web_plan()))

    plan = project.create_plan("开发一个待办事项 Web 应用，包含任务列表页面")

    assert project.last_project_profile.project_type == "web"
    assert [task["role"] for task in plan["tasks"]].count("ui_ux") == 1

    manager = project.build_task_manager(plan)
    ux_task = manager.get_task("UX-001")
    assert ux_task.context["project_type"] == "web"
    assert manager.get_task("DEV-001").context["developer_specialist"] == "frontend"
    assert manager.get_task("DEV-002").context["developer_specialist"] == "backend"


def test_create_plan_does_not_inject_ui_ux_without_registered_agent():
    project = ProjectOrchestrator(agent_router=_UiUxRouter(_web_plan(), with_ui_ux=False))

    plan = project.create_plan("开发一个待办事项 Web 应用，包含任务列表页面")

    assert project.last_project_profile.ui_required is True
    assert all(task["role"] != "ui_ux" for task in plan["tasks"])


def test_cli_plan_keeps_no_ui_ux_and_no_ui_context():
    project = ProjectOrchestrator(agent_router=_UiUxRouter(_cli_plan()))

    plan = project.create_plan("开发一个命令行 todo 工具，支持 add/list/done 子命令")
    manager = project.build_task_manager(plan)

    assert project.last_project_profile.project_type == "cli"
    assert all(task["role"] != "ui_ux" for task in plan["tasks"])
    task = manager.get_task("DEV-001")
    assert task.context["project_type"] == "cli"
    assert task.context["developer_specialist"] == "cli"


def test_ui_ux_spec_digest_collects_completed_design_task():
    manager = ProjectOrchestrator._ui_ux_spec_digest

    class _Manager:
        def get_all_tasks(self):
            return [
                Task(
                    id="UX-001",
                    title="UI/UX 设计规范",
                    description="设计",
                    role="ui_ux",
                    status="completed",
                    context={"project_type": "web"},
                    result={"message": "spec body"},
                )
            ]

    digest = manager(_Manager())

    assert digest == {"task_id": "UX-001", "project_type": "web", "spec": "spec body"}
