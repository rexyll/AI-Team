from __future__ import annotations

from pathlib import Path

from core import project_orchestrator as project_module
from core.project_orchestrator import ProjectOrchestrator
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_result import ToolResult
from security.workspace import resolve_workspace_path


class _FakeInvocationService:
    def __init__(self, *, fail_on: int | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail_on = fail_on
        self._history = ToolExecutionHistory()

    @property
    def history(self) -> ToolExecutionHistory:
        return self._history

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        # The executor must run while the deliverable is the active sandbox.
        assert resolve_workspace_path(".").is_dir()
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            return ToolResult.ok("exit_code=17\nfixture command failed")
        return ToolResult.ok("exit_code=0\nfixture command passed")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_project_adapter_phase_is_opt_in(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AI_TEAM_PROJECT_ADAPTERS", raising=False)
    orchestrator = ProjectOrchestrator(agent_router=object())

    result = orchestrator._run_project_adapter_phase(tmp_path)

    assert result["status"] == "disabled"
    assert result["actions"] == {}


def test_project_adapter_phase_executes_through_tool_service_in_workspace_scope(
    monkeypatch, tmp_path: Path
) -> None:
    _write(
        tmp_path / "pyproject.toml",
        "[build-system]\nrequires = ['setuptools>=75']\nbuild-backend = 'setuptools.build_meta'\n"
        "[project]\nname = 'adapter-orchestrator-fixture'\nversion = '0.1.0'\n",
    )
    _write(tmp_path / "tests" / "test_fixture.py", "def test_ok(): assert True\n")
    service = _FakeInvocationService()
    monkeypatch.setenv("AI_TEAM_PROJECT_ADAPTERS", "1")
    monkeypatch.setattr(project_module, "ToolInvocationService", lambda: service)
    orchestrator = ProjectOrchestrator(agent_router=object(), project_id="fixture")

    result = orchestrator._run_project_adapter_phase(tmp_path)

    assert result["status"] == "passed"
    assert result["adapter"] == "python"
    assert set(result["actions"]) == {"install", "build", "test", "smoke", "package"}
    assert all(call["role"] == "developer" for call in service.calls)
    assert all(call["tool_name"] == "run_command" for call in service.calls)
    assert all(call["arguments"]["cwd"] == "." for call in service.calls)
    assert all(1 <= call["arguments"]["timeout"] <= 3600 for call in service.calls)
    assert len(service.calls) == 5


def test_project_adapter_phase_stops_on_first_failed_command(monkeypatch, tmp_path: Path) -> None:
    _write(tmp_path / "package.json", '{"name":"fixture","scripts":{"build":"node build.js"}}')
    _write(tmp_path / "package-lock.json", '{"name":"fixture","lockfileVersion":3,"packages":{"":{"name":"fixture"}}}')
    service = _FakeInvocationService(fail_on=1)
    monkeypatch.setenv("AI_TEAM_PROJECT_ADAPTERS", "1")
    monkeypatch.setattr(project_module, "ToolInvocationService", lambda: service)
    orchestrator = ProjectOrchestrator(agent_router=object())

    result = orchestrator._run_project_adapter_phase(tmp_path)

    assert result["status"] == "failed"
    assert result["failed_action"] == "install"
    assert list(result["actions"]) == ["install"]
    assert len(service.calls) == 1


def test_project_adapter_phase_rejects_ambiguous_toolchains(monkeypatch, tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", "[project]\nname='fixture'\nversion='0.1.0'\n")
    _write(tmp_path / "package.json", '{"name":"fixture"}')
    monkeypatch.setenv("AI_TEAM_PROJECT_ADAPTERS", "1")
    orchestrator = ProjectOrchestrator(agent_router=object())

    result = orchestrator._run_project_adapter_phase(tmp_path)

    assert result["status"] == "unsupported"
    assert "multiple project adapters" in result["reason"]


def test_integration_phase_includes_adapter_gate_evidence(monkeypatch, tmp_path: Path) -> None:
    _write(tmp_path / "package.json", '{"name":"fixture","scripts":{"build":"node build.js"}}')
    _write(tmp_path / "package-lock.json", '{"name":"fixture","lockfileVersion":3,"packages":{"":{"name":"fixture"}}}')
    service = _FakeInvocationService()
    monkeypatch.setenv("AI_TEAM_PROJECT_ADAPTERS", "1")
    monkeypatch.setenv("AI_TEAM_STATIC_GATE", "0")
    monkeypatch.setenv("AI_TEAM_INTEGRATION_MAX_ROUNDS", "0")
    monkeypatch.setattr(project_module, "ToolInvocationService", lambda: service)
    monkeypatch.setattr(
        project_module,
        "run_integration_suite",
        lambda root, timeout: {
            "status": "skipped",
            "reason": "fixture has no tests",
            "test_files": [],
            "command": None,
            "exit_code": None,
            "summary": None,
            "output_tail": "",
        },
    )
    orchestrator = ProjectOrchestrator(agent_router=object())

    result = orchestrator._run_integration_phase(tmp_path)

    assert result["status"] == "skipped"
    assert result["adapter"]["status"] == "passed"
    assert result["adapter"]["adapter"] == "node"
