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
        def __init__(self, agent_router):
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
        def __init__(self, agent_router):
            self.agent_router = agent_router

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
        def __init__(self, agent_router):
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
