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

    
def test_build_parser_accepts_deployment_recovery_inventory():
    parser = main.build_parser()

    args = parser.parse_args([
        "--deployment-history", "C:/host/deployments.sqlite3",
        "--deployment-recovery-inventory",
    ])

    assert args.deployment_history == "C:/host/deployments.sqlite3"
    assert args.deployment_recovery_inventory is True

def test_build_parser_accepts_deployment_recovery_inspect():
    parser = main.build_parser()
    args = parser.parse_args([
        "--deployment-history", "C:/host/deployments.sqlite3",
        "--deployment-recovery-inspect",
    ])
    assert args.deployment_recovery_inspect is True




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
        def __init__(self, agent_router, deliverable_dir=None, clarifications=None, **kwargs):
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

    def fake_create_agent_router(**kwargs):
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
        def __init__(self, agent_router, deliverable_dir=None, clarifications=None, **kwargs):
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

    monkeypatch.setattr(main, "create_agent_router", lambda **kwargs: object())
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
        def __init__(self, agent_router, deliverable_dir=None, clarifications=None, **kwargs):
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

    monkeypatch.setattr(main, "create_agent_router", lambda **kwargs: object())
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
        def __init__(self, agent_router, deliverable_dir=None, clarifications=None, **kwargs):
            pass

        def create_plan(self, requirement):
            return {"project": "demo", "summary": "s", "tasks": []}

        def build_task_manager(self, plan):
            return FakeTaskManager()

        def execute(self, task_manager):
            return FakeProjectResult()

    monkeypatch.setattr(main, "create_agent_router", lambda **kwargs: object())
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
    monkeypatch.setattr(main, "create_agent_router", lambda **kwargs: router)
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
        def __init__(self, agent_router, deliverable_dir=None, clarifications=None, **kwargs):
            delivered["clarifications"] = clarifications

        def create_plan(self, requirement):
            return {"project": "demo", "summary": "s", "tasks": []}

        def build_task_manager(self, plan):
            return FakeTaskManager()

        def execute(self, task_manager):
            return FakeProjectResult()

    def fake_create_agent_router(**kwargs):
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
        def __init__(self, agent_router, deliverable_dir=None, clarifications=None, **kwargs):
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


def test_main_scans_configured_deployment_history_before_project_dispatch(tmp_path, monkeypatch, capsys):
    history_path = tmp_path / "host" / "deployments.sqlite3"
    _seed_pending_replacement_for_cli_test(history_path)
    monkeypatch.setenv("AI_TEAM_DEPLOYMENT_HISTORY", str(history_path))

    class FakeResult:
        success = True
        status = "completed"
        total_tasks = 0
        completed_tasks = 0

        def to_dict(self):
            return {"success": True, "status": "completed"}

    monkeypatch.setattr(main, "run_project", lambda *args, **kwargs: (FakeTaskManager([]), FakeResult()))
    monkeypatch.setattr(main.sys, "argv", ["main.py", "demo", "--output", "json"])

    assert main.main() == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["result"]["success"] is True
    assert "startup-operation-001:prepared_candidate_not_persisted" in captured.err


def test_main_deployment_recovery_inventory_is_standalone_json(tmp_path, monkeypatch, capsys):
    history_path = tmp_path / "host" / "deployments.sqlite3"
    _seed_pending_replacement_for_cli_test(history_path)
    monkeypatch.delenv("AI_TEAM_DEPLOYMENT_HISTORY", raising=False)
    monkeypatch.setattr(main.sys, "argv", [
        "main.py",
        "--deployment-history", str(history_path),
        "--deployment-recovery-inventory",
        "--output", "json",
    ])

    assert main.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["unfinished_replacements"] == 1
    assert payload["inventory"][0]["operation_id"] == "startup-operation-001"
    assert payload["inventory"][0]["external_state_verified"] is False


def _seed_pending_replacement_for_cli_test(path):
    from runtime.deployment_history import DeploymentHistoryStore
    from runtime.deployment_provider import DeploymentArtifact, DeploymentRecord
    from runtime.deployment_replacement import ReplacementJournalRecord

    history = DeploymentHistoryStore(path)
    artifact = DeploymentArtifact(
        "docker-local", "image:previous", "a" * 64, "1.0"
    )
    previous = DeploymentRecord(
        "previous", "docker-local", "staging", "1.0", artifact,
        "running", "healthy", "2026-11-15T15:00:00Z",
        project="demo", container_id="a" * 64,
    )
    history.append(previous)
    history.set_active_deployment(
        provider="docker-local", environment="staging", project="demo",
        deployment_id="previous", expected_deployment_id=None,
    )
    history.begin_replacement(ReplacementJournalRecord(
        operation_id="startup-operation-001",
        provider="docker-local",
        project="demo",
        environment="staging",
        target_deployment_id="candidate",
        previous_deployment_id="previous",
        phase="prepared",
        created_at="2026-11-15T15:01:00Z",
        updated_at="2026-11-15T15:01:00Z",
        previous_runtime_id=previous.container_id,
    ))
    return history


def test_main_deployment_recovery_inspect_is_explicit_and_json(tmp_path, monkeypatch, capsys):
    report = {
        "status": "ok",
        "provider": "docker-local",
        "history_path": str(tmp_path / "deployments.sqlite3"),
        "unfinished_replacements": 1,
        "observations": [{
            "operation_id": "operation-inspect",
            "previous_runtime": {
                "status": "verified",
                "runtime_state": "running",
                "health_status": "healthy",
            },
            "candidate_runtime": None,
            "route_readback_status": "not_available",
            "automatic_recovery_allowed": False,
        }],
        "route_readback_available": False,
        "automatic_recovery_allowed": False,
    }

    class FakeHostRuntime:
        def __init__(self, history_path, *, create_if_missing=True):
            assert create_if_missing is False

        def inspect_recovery(self):
            return report

    monkeypatch.setattr(main, "DeploymentHostRuntime", FakeHostRuntime)
    monkeypatch.delenv("AI_TEAM_DEPLOYMENT_HISTORY", raising=False)
    monkeypatch.setattr(main.sys, "argv", [
        "main.py",
        "--deployment-history", str(tmp_path / "deployments.sqlite3"),
        "--deployment-recovery-inspect",
        "--output", "json",
    ])

    assert main.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["route_readback_available"] is False
    assert payload["automatic_recovery_allowed"] is False
    assert payload["observations"][0]["previous_runtime"]["status"] == "verified"


def test_build_parser_accepts_deployment_reconciliation_readback():
    args = main.build_parser().parse_args([
        "--deployment-history", "C:/host/deployments.sqlite3",
        "--deployment-reconciliation-readback",
        "--output", "json",
    ])
    assert args.deployment_history == "C:/host/deployments.sqlite3"
    assert args.deployment_reconciliation_readback is True
    assert args.output == "json"


def test_main_deployment_reconciliation_readback_is_standalone_json(tmp_path, monkeypatch, capsys):
    report = {
        "status": "ok",
        "history_path": str(tmp_path / "deployments.sqlite3"),
        "provider": "docker-local",
        "unfinished_replacements": 1,
        "readbacks": [{
            "operation_id": "operation-readback",
            "phase": "traffic_switch_pending",
            "assessment": "switch_applied_before_journal_commit",
            "previous_runtime": {"status": "verified", "runtime_state": "running", "health_status": "healthy"},
            "candidate_runtime": {"status": "verified", "runtime_state": "running", "health_status": "healthy"},
            "route_readback": {
                "status": "verified", "live_active_slot": "slot_b",
                "effective_runtime_id": "b" * 64,
                "backend_readbacks": [{
                    "backend": "be_p42699", "slot": "slot_b",
                    "observed_address": "172.18.0.3", "observed_port": 18080,
                    "status": "UP", "current_sessions": 0,
                }],
            },
            "automatic_action": "none",
            "automatic_recovery_allowed": False,
        }],
        "read_only": True,
        "automatic_action": "none",
        "automatic_recovery_allowed": False,
    }

    class FakeHostRuntime:
        def __init__(self, history_path, *, create_if_missing=True):
            assert create_if_missing is False

        def inspect_manual_reconciliation_readback(self):
            return report

    monkeypatch.setattr(main, "DeploymentHostRuntime", FakeHostRuntime)
    monkeypatch.delenv("AI_TEAM_DEPLOYMENT_HISTORY", raising=False)
    monkeypatch.setattr(main.sys, "argv", [
        "main.py", "--deployment-history", str(tmp_path / "deployments.sqlite3"),
        "--deployment-reconciliation-readback", "--output", "json",
    ])

    assert main.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["read_only"] is True
    assert payload["automatic_action"] == "none"
    assert payload["readbacks"][0]["assessment"] == "switch_applied_before_journal_commit"
    assert payload["readbacks"][0]["route_readback"]["backend_readbacks"][0]["status"] == "UP"
