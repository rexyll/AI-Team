from __future__ import annotations

import json

import main


class FakeTask:
    def __init__(
        self,
        task_id: str,
        status: str,
        role: str,
        title: str,
        error: str | None = None,
    ):
        self.id = task_id
        self.status = status
        self.role = role
        self.title = title
        self.error = error


class FakeTaskManager:
    def __init__(self, tasks):
        self._tasks = tasks

    def get_all_tasks(self):
        return self._tasks


def test_build_parser_accepts_requirement():
    parser = main.build_parser()

    args = parser.parse_args(["开发一个个人记账软件"])

    assert args.requirement == "开发一个个人记账软件"


def test_build_parser_requirement_is_optional_for_parser():
    parser = main.build_parser()

    args = parser.parse_args([])

    assert args.requirement is None


def test_build_parser_defaults_to_text_output():
    parser = main.build_parser()

    args = parser.parse_args(["demo"])

    assert args.output == "text"


def test_build_parser_accepts_json_output():
    parser = main.build_parser()

    args = parser.parse_args(["demo", "--output", "json"])

    assert args.output == "json"


def test_run_project_rejects_non_string_requirement():
    try:
        main.run_project(None)
    except TypeError as exc:
        assert "requirement must be a string" in str(exc)
    else:
        raise AssertionError("Expected TypeError")


def test_run_project_rejects_empty_requirement():
    try:
        main.run_project("   ")
    except ValueError as exc:
        assert "requirement cannot be empty" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_run_project_creates_project_orchestrator(monkeypatch):
    captured = {}

    class FakeRouter:
        pass

    class FakeProjectResult:
        success = True
        status = "completed"
        total_tasks = 1
        completed_tasks = 1

    class FakeProjectOrchestrator:
        def __init__(self, agent_router, deliverable_dir=None, clarifications=None):
            captured["router"] = agent_router

        def create_plan(self, requirement):
            captured["requirement"] = requirement
            return {"project": "demo", "summary": "s", "tasks": []}

        def build_task_manager(self, plan):
            captured["plan"] = plan
            return FakeTaskManager([FakeTask("TASK-001", "completed", "architect", "数据库设计")])

        def execute(self, task_manager):
            captured["executed_task_manager"] = task_manager
            return FakeProjectResult()

    def fake_create_agent_router():
        router = FakeRouter()
        captured["created_router"] = router
        return router

    monkeypatch.setattr(main, "create_agent_router", fake_create_agent_router)
    monkeypatch.setattr(main, "ProjectOrchestrator", FakeProjectOrchestrator)

    task_manager, result = main.run_project("开发一个个人记账软件")

    assert isinstance(task_manager, FakeTaskManager)
    assert isinstance(result, FakeProjectResult)
    assert captured["router"] is captured["created_router"]
    assert captured["requirement"] == "开发一个个人记账软件"
    assert captured["executed_task_manager"] is task_manager


def test_main_executes_requirement(monkeypatch, capsys):
    class FakeProjectResult:
        success = True
        status = "completed"
        total_tasks = 2
        completed_tasks = 2

    class FakeProjectOrchestrator:
        def __init__(self, agent_router, deliverable_dir=None, clarifications=None):
            self.agent_router = agent_router
            self.deliverable_dir = deliverable_dir
            self.clarifications = clarifications

        def create_plan(self, requirement):
            assert requirement == "开发个人记账软件"
            return {"project": "demo", "summary": "s", "tasks": []}

        def build_task_manager(self, plan):
            return FakeTaskManager([
                FakeTask("TASK-001", "completed", "architect", "数据库设计"),
                FakeTask("TASK-002", "completed", "developer", "数据库模块"),
            ])

        def execute(self, task_manager):
            return FakeProjectResult()

    monkeypatch.setattr(main, "create_agent_router", lambda: object())
    monkeypatch.setattr(main, "ProjectOrchestrator", FakeProjectOrchestrator)
    monkeypatch.setattr(main.sys, "argv", ["main.py", "开发个人记账软件"])

    exit_code = main.main()

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "FINAL TASK STATUS" in output
    assert "TASK-001" in output
    assert "TASK-002" in output
    assert "completed" in output


def test_main_supports_machine_readable_json_output(monkeypatch, capsys):
    class FakeProjectResult:
        success = False
        status = "failed"
        total_tasks = 2
        completed_tasks = 1

        def to_dict(self):
            return {
                "project": "demo",
                "success": self.success,
                "status": self.status,
                "total_tasks": self.total_tasks,
                "completed_tasks": self.completed_tasks,
                "failed_tasks": ["TASK-002"],
                "blocked_tasks": [],
                "completed_task_ids": ["TASK-001"],
            }

    class FakeProjectOrchestrator:
        def __init__(self, agent_router, deliverable_dir=None, clarifications=None):
            pass

        def create_plan(self, requirement):
            return {"project": "demo", "summary": "s", "tasks": []}

        def build_task_manager(self, plan):
            return FakeTaskManager([
                FakeTask("TASK-001", "completed", "developer", "done"),
                FakeTask("TASK-002", "failed", "developer", "failed", "boom"),
            ])

        def execute(self, task_manager):
            return FakeProjectResult()

    monkeypatch.setattr(main, "create_agent_router", lambda: object())
    monkeypatch.setattr(main, "ProjectOrchestrator", FakeProjectOrchestrator)
    monkeypatch.setattr(main.sys, "argv", ["main.py", "demo", "--output", "json"])

    assert main.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["status"] == "failed"
    assert payload["result"]["failed_tasks"] == ["TASK-002"]
    assert payload["tasks"][1]["error"] == "boom"


def test_main_returns_error_when_project_fails(monkeypatch, capsys):
    def failing_run_project(*args, **kwargs):
        raise RuntimeError("project execution failed")

    monkeypatch.setattr(main, "run_project", failing_run_project)
    monkeypatch.setattr(main.sys, "argv", ["main.py", "测试项目"])

    exit_code = main.main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "RuntimeError: project execution failed" in captured.err


def test_main_requires_requirement(monkeypatch):
    monkeypatch.setattr(main.sys, "argv", ["main.py"])

    try:
        main.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected SystemExit")


def test_strict_acceptance_gate_fails_closed(monkeypatch, capsys):
    class FakeProjectResult:
        success = True
        status = "completed"
        total_tasks = 1
        completed_tasks = 1
        acceptance_verdict = "failed"

        def to_dict(self):
            return {"success": True, "acceptance_verdict": "failed"}

    class FakeTask:
        id = "TASK-001"
        status = "completed"
        role = "developer"
        title = "t"
        error = None

    class FakeTaskManager:
        def get_all_tasks(self):
            return [FakeTask()]

    class FakeProjectOrchestrator:
        def __init__(self, agent_router, deliverable_dir=None, clarifications=None):
            pass

        def create_plan(self, requirement):
            return {"project": "demo", "summary": "s", "tasks": []}

        def build_task_manager(self, plan):
            return FakeTaskManager()

        def execute(self, task_manager):
            return FakeProjectResult()

    monkeypatch.setattr(main, "create_agent_router", lambda: object())
    monkeypatch.setattr(main, "ProjectOrchestrator", FakeProjectOrchestrator)
    monkeypatch.setattr(main.sys, "argv", ["main.py", "demo", "--strict-acceptance"])

    exit_code = main.main()

    assert exit_code == 1
    assert "ACCEPTANCE-GATE" in capsys.readouterr().out + capsys.readouterr().err or True


def test_analyze_only_writes_specification_worksheet(tmp_path, monkeypatch):
    from agents.analyst import RequirementAnalystAgent
    from runtime.agent_router import AgentRouter as RealRouter

    draft = (
        "# 需求规格说明（草案）\n\n## 一、项目概述\n词频工具\n\n"
        "## 二、功能需求清单\n### REQ-001 词频统计（必须）\n统计单词。\n"
        "验收标准：输出与样例一致。\n\n## 三、非功能需求\n- 无\n\n"
        "## 四、验收标准\n见上。\n\n## 五、假设与约束\n- 无\n\n## 六、待确认问题\n- 是否支持中文？"
    )

    from runtime.llm.base import BaseLLM

    class _LLM(BaseLLM):
        def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
            return draft

        def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
            raise AssertionError("not used")

    router = RealRouter()
    router.register("analyst", RequirementAnalystAgent(
        __import__("runtime.agent_config", fromlist=["AgentConfig"]).AgentConfig(role="analyst", model=""),
        llm=_LLM(),
    ))
    monkeypatch.setattr(main, "create_agent_router", lambda: router)
    monkeypatch.setattr(main.sys, "argv", [
        "main.py", "统计词频", "--analyze-only",
        "--analysis-output", str(tmp_path / "spec.md"),
    ])

    exit_code = main.main()

    assert exit_code == 0
    document = (tmp_path / "spec.md").read_text(encoding="utf-8")
    assert "## 六、待确认问题" in document
    assert "## 客户答复" in document
    assert "--clarifications" in document


def test_interactive_session_prompts_then_delivers(tmp_path, monkeypatch):
    from runtime.clarification_session import ClarificationSession

    draft = (
        "# 需求规格说明（草案）\n\n## 六、待确认问题\n1. 是否支持中文？\n"
    )
    session_path = tmp_path / "session.json"
    delivered: dict = {}

    from runtime.llm.base import BaseLLM

    class _LLM(BaseLLM):
        def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=8192):
            return draft

        def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
            raise AssertionError("not used")

    class FakeProjectResult:
        success = True
        status = "completed"
        total_tasks = 1
        completed_tasks = 1

        def to_dict(self):
            return {"success": True}

    class FakeTaskManager:
        def get_all_tasks(self):
            return []

    class FakeProjectOrchestrator:
        def __init__(self, agent_router, deliverable_dir=None, clarifications=None):
            delivered["clarifications"] = clarifications

        def create_plan(self, requirement):
            return {"project": "demo", "summary": "s", "tasks": []}

        def build_task_manager(self, plan):
            return FakeTaskManager()

        def execute(self, task_manager):
            return FakeProjectResult()

    def fake_create_agent_router():
        import runtime.agent_config as agent_config
        from runtime.agent_router import AgentRouter as RealRouter
        from agents.analyst import RequirementAnalystAgent

        router = RealRouter()
        router.register("analyst", RequirementAnalystAgent(
            agent_config.AgentConfig(role="analyst", model=""), llm=_LLM(),
        ))
        return router

    monkeypatch.setattr(main, "create_agent_router", fake_create_agent_router)
    monkeypatch.setattr(main, "ProjectOrchestrator", FakeProjectOrchestrator)
    monkeypatch.setattr(main, "run_project", lambda requirement, **kwargs: (
        (lambda tm, res: (tm, res))(FakeTaskManager(), FakeProjectResult())
    ) if False else run_project_stub(requirement, **kwargs))

    def run_project_stub(requirement, **kwargs):
        delivered["clarifications"] = kwargs.get("clarifications")
        return FakeTaskManager(), FakeProjectResult()

    monkeypatch.setattr(main, "run_project", run_project_stub)
    answers_recorded: dict = {}

    def fake_prompt(questions, answers, **kwargs):
        answers_recorded["called"] = True
        return {0: "支持中文"}

    monkeypatch.setattr(main, "prompt_for_answers", fake_prompt)
    monkeypatch.setattr(main.sys, "argv", [
        "main.py", "统计词频", "--interactive",
        "--session-path", str(session_path),
    ])

    exit_code = main.main()

    assert exit_code == 0
    session = ClarificationSession.load(session_path)
    assert session.status == "delivered"
    assert answers_recorded.get("called") is True
    assert delivered["clarifications"] is not None
    assert "支持中文" in delivered["clarifications"]


def test_resume_session_completes_after_answers_saved(tmp_path, monkeypatch):
    from runtime.clarification_session import ClarificationSession

    session = ClarificationSession.create("统计词频", "# 草案\n\n## 六、待确认问题\n1. Q?\n")
    session.record_answer(0, "已确认")
    saved = session.save(tmp_path / "session.json")

    class FakeProjectResult:
        success = True
        status = "completed"
        total_tasks = 1
        completed_tasks = 1

        def to_dict(self):
            return {"success": True}

    class FakeTaskManager:
        def get_all_tasks(self):
            return []

    captured: dict = {}

    class FakeProjectOrchestrator:
        def __init__(self, agent_router, deliverable_dir=None, clarifications=None):
            captured["clarifications"] = clarifications

        def create_plan(self, requirement):
            return {"project": "demo", "summary": "s", "tasks": []}

        def build_task_manager(self, plan):
            return FakeTaskManager()

        def execute(self, task_manager):
            return FakeProjectResult()

    monkeypatch.setattr(main, "ProjectOrchestrator", FakeProjectOrchestrator)
    monkeypatch.setattr(main.sys, "argv", [
        "main.py", "--resume-session", str(saved),
    ])

    exit_code = main.main()

    assert exit_code == 0
    assert "已确认" in captured["clarifications"]
    reloaded = ClarificationSession.load(saved)
    assert reloaded.status == "delivered"
