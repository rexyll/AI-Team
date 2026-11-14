from __future__ import annotations

from pathlib import Path

from core import project_orchestrator as project_module
from core.project_orchestrator import ProjectOrchestrator
from runtime.tool_invocation_service import ToolInvocationService
from security.workspace import resolve_workspace_path
from tools.registry import ToolRegistry


def _service_with_stub_command(*, fail_on: int | None = None):
    calls: list[dict[str, object]] = []

    def run_command(command: str, cwd: str = ".", timeout: float = 600.0) -> str:
        working_directory = resolve_workspace_path(cwd)
        assert working_directory.is_dir()
        calls.append({
            "command": command,
            "cwd": cwd,
            "timeout": timeout,
            "workspace": working_directory,
        })
        exit_code = 17 if fail_on == len(calls) else 0
        return f"exit_code={exit_code}\nfixture command"

    registry = ToolRegistry()
    registry.register(
        "run_command",
        run_command,
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "cwd": {"type": "string"},
                        "timeout": {"type": "number", "minimum": 1, "maximum": 3600},
                    },
                    "required": ["command"],
                },
            },
        },
    )
    return ToolInvocationService(registry=registry), calls


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_project_adapter_phase_is_opt_in(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AI_TEAM_PROJECT_ADAPTERS", raising=False)
    orchestrator = ProjectOrchestrator(agent_router=object())

    result = orchestrator._run_project_adapter_phase(tmp_path)

    assert result["status"] == "disabled"
    assert result["actions"] == {}


def test_project_adapter_phase_uses_real_tool_invocation_service_and_workspace_scope(
    monkeypatch, tmp_path: Path
) -> None:
    _write(
        tmp_path / "pyproject.toml",
        "[build-system]\nrequires = ['setuptools>=75']\nbuild-backend = 'setuptools.build_meta'\n"
        "[project]\nname = 'adapter-orchestrator-fixture'\nversion = '0.1.0'\n",
    )
    _write(tmp_path / "tests" / "test_fixture.py", "def test_ok(): assert True\n")
    service, calls = _service_with_stub_command()
    monkeypatch.setenv("AI_TEAM_PROJECT_ADAPTERS", "1")
    monkeypatch.setattr(project_module, "ToolInvocationService", lambda: service)
    orchestrator = ProjectOrchestrator(agent_router=object(), project_id="fixture")

    result = orchestrator._run_project_adapter_phase(tmp_path)

    assert result["status"] == "passed", result
    assert result["adapter"] == "python"
    assert set(result["actions"]) == {"install", "build", "test", "smoke", "package"}
    assert len(calls) == 5
    assert all(call["cwd"] == "." for call in calls)
    assert all(1 <= call["timeout"] <= 3600 for call in calls)
    records = service.history.to_dict()
    assert len(records) == 5
    assert all(record["agent_role"] == "developer" for record in records)
    assert all(record["tool_name"] == "run_command" for record in records)
    assert all(record["status"] == "completed" for record in records)
    assert len(result["tool_execution_history"]) == 5


def test_project_adapter_phase_stops_on_first_failed_command(monkeypatch, tmp_path: Path) -> None:
    _write(tmp_path / "package.json", '{"name":"fixture","scripts":{"build":"node build.js"}}')
    _write(tmp_path / "package-lock.json", '{"name":"fixture","lockfileVersion":3,"packages":{"":{"name":"fixture"}}}')
    service, calls = _service_with_stub_command(fail_on=1)
    monkeypatch.setenv("AI_TEAM_PROJECT_ADAPTERS", "1")
    monkeypatch.setattr(project_module, "ToolInvocationService", lambda: service)
    orchestrator = ProjectOrchestrator(agent_router=object())

    result = orchestrator._run_project_adapter_phase(tmp_path)

    assert result["status"] == "failed"
    assert result["failed_action"] == "install"
    assert list(result["actions"]) == ["install"]
    assert len(calls) == 1
    assert service.history.to_dict()[0]["status"] == "completed"


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
    service, _ = _service_with_stub_command()
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

    assert result["status"] == "skipped", result
    assert result["adapter"]["status"] == "passed"
    assert result["adapter"]["adapter"] == "node"


def test_integration_phase_fails_closed_on_adapter_command_failure(monkeypatch, tmp_path: Path) -> None:
    _write(tmp_path / "package.json", '{"name":"fixture","scripts":{"build":"node build.js"}}')
    _write(tmp_path / "package-lock.json", '{"name":"fixture","lockfileVersion":3,"packages":{"":{"name":"fixture"}}}')
    service, _ = _service_with_stub_command(fail_on=1)
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

    assert result["status"] == "failed"
    assert result["suite"]["adapter_failure"]["failed_action"] == "install"
    assert result["adapter"]["status"] == "failed"
