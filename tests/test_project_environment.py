from __future__ import annotations

from pathlib import Path

import core.orchestrator as orchestrator_module
from core.orchestrator import Orchestrator
from runtime.project_environment import ProjectEnvironmentProvisioner
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.tool_invocation_service import ToolInvocationService
from security.workspace import resolve_workspace_path, workspace_scope
from tools.filesystem import write_file
from tools.registry import ToolRegistry


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _service_with_stub_install(*, fail_on: int | None = None):
    calls: list[dict[str, object]] = []

    def run_command(command: str, cwd: str = ".", timeout: float = 600.0) -> str:
        root = resolve_workspace_path(cwd)
        calls.append({"command": command, "root": root, "timeout": timeout})
        if command == "python -m venv --system-site-packages .venv":
            (root / ".venv").mkdir()
        exit_code = 9 if fail_on == len(calls) else 0
        return f"exit_code={exit_code}\nfixture install"

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


class _DeveloperRouter:
    def get_developer_for_task(self, task_id: str):
        return object()

    def get_agent(self, role: str):
        return object()


def test_environment_provisioner_installs_inside_the_supplied_lease(tmp_path: Path) -> None:
    _write(tmp_path / "requirements.txt", "pytest\n")
    service, calls = _service_with_stub_install()
    provisioner = ProjectEnvironmentProvisioner(invocation_service=service)

    with workspace_scope(tmp_path):
        result = provisioner.prepare(
            tmp_path,
            task_id="TASK-ENV-001",
            execution_id="TASK-ENV-EXEC-001",
        )

    assert result["status"] == "passed"
    assert result["adapter"] == "python"
    assert (tmp_path / ".venv").is_dir()
    assert len(calls) == 2
    assert all(call["root"] == tmp_path.resolve() for call in calls)
    assert len(service.audit.records()) == 2
    assert all(record.agent_role == "developer" for record in service.audit.records())


def test_environment_provisioner_skips_projects_without_supported_manifests(tmp_path: Path) -> None:
    provisioner = ProjectEnvironmentProvisioner(invocation_service=_service_with_stub_install()[0])

    result = provisioner.prepare(
        tmp_path,
        task_id="TASK-ENV-002",
        execution_id="TASK-ENV-EXEC-002",
    )

    assert result["status"] == "skipped"


def test_environment_provisioner_rejects_ambiguous_project_toolchains(tmp_path: Path) -> None:
    _write(tmp_path / "requirements.txt", "pytest\n")
    _write(tmp_path / "package.json", '{"name":"ambiguous"}')
    provisioner = ProjectEnvironmentProvisioner(invocation_service=_service_with_stub_install()[0])

    result = provisioner.prepare(
        tmp_path,
        task_id="TASK-ENV-003",
        execution_id="TASK-ENV-EXEC-003",
    )

    assert result["status"] == "unsupported"
    assert "multiple project adapters" in result["reason"]


def test_environment_install_failure_is_reported_without_claiming_prepared(tmp_path: Path) -> None:
    _write(tmp_path / "requirements.txt", "pytest\n")
    service, _ = _service_with_stub_install(fail_on=2)
    provisioner = ProjectEnvironmentProvisioner(invocation_service=service)

    with workspace_scope(tmp_path):
        result = provisioner.prepare(
            tmp_path,
            task_id="TASK-ENV-004",
            execution_id="TASK-ENV-EXEC-004",
        )

    assert result["status"] == "failed"
    assert result["action"]["steps"][-1]["exit_code"] == 9
    assert len(service.audit.records()) == 2


def test_orchestrator_prepares_environment_in_lease_and_never_merges_it(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    _write(root / "requirements.txt", "pytest\n")
    task = Task(
        id="TASK-ENV-005",
        title="develop with isolated dependencies",
        description="write a source artifact",
        role="developer",
        status="ready",
        context={"workspace_root": str(root)},
    )
    manager = TaskManager([task])
    service, calls = _service_with_stub_install()
    provisioner = ProjectEnvironmentProvisioner(invocation_service=service)
    observed = {"environment_visible": False}

    class _Workflow:
        def execute(self, task_id: str, *, execution_id: str | None = None):
            observed["environment_visible"] = (resolve_workspace_path(".") / ".venv").is_dir()
            write_file("generated.py", "VALUE = 42\n")
            manager.get_task(task_id).status = "completed"

    monkeypatch.setenv("AI_TEAM_TASK_ENVIRONMENTS", "1")
    monkeypatch.setattr(
        orchestrator_module,
        "ProjectEnvironmentProvisioner",
        lambda: provisioner,
    )
    monkeypatch.setattr(
        orchestrator_module,
        "create_task_workflow",
        lambda **kwargs: _Workflow(),
    )
    orchestrator = Orchestrator(manager, _DeveloperRouter())

    orchestrator._execute_task(task, execution_id="TASK-ENV-EXEC-005")

    assert observed["environment_visible"] is True
    assert len(calls) == 2
    assert all(call["root"] != root.resolve() for call in calls)
    assert task.status == "completed"
    assert task.context["workspace_environment"]["status"] == "passed"
    assert (root / "generated.py").read_text(encoding="utf-8") == "VALUE = 42\n"
    assert not (root / ".venv").exists()
    assert not list((root.parent / ".ai-team-dev-workspaces").glob("TASK-ENV-005-*"))


def test_orchestrator_fails_task_and_discards_lease_when_environment_install_fails(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "deliverable"
    root.mkdir()
    _write(root / "requirements.txt", "pytest\n")
    task = Task(
        id="TASK-ENV-006",
        title="must not run without dependencies",
        description="do not execute developer workflow",
        role="developer",
        status="ready",
        max_retries=0,
        context={"workspace_root": str(root)},
    )
    manager = TaskManager([task])
    service, _ = _service_with_stub_install(fail_on=2)
    provisioner = ProjectEnvironmentProvisioner(invocation_service=service)

    class _Workflow:
        def execute(self, task_id: str, *, execution_id: str | None = None):
            raise AssertionError("workflow must not run after environment setup fails")

    monkeypatch.setenv("AI_TEAM_TASK_ENVIRONMENTS", "1")
    monkeypatch.setattr(
        orchestrator_module,
        "ProjectEnvironmentProvisioner",
        lambda: provisioner,
    )
    monkeypatch.setattr(
        orchestrator_module,
        "create_task_workflow",
        lambda **kwargs: _Workflow(),
    )
    orchestrator = Orchestrator(manager, _DeveloperRouter())

    orchestrator._execute_task(task, execution_id="TASK-ENV-EXEC-006")

    assert task.status == "failed"
    assert task.context["workspace_environment"]["status"] == "failed"
    assert not (root / "generated.py").exists()
    assert not (root / ".venv").exists()
    assert not list((root.parent / ".ai-team-dev-workspaces").glob("TASK-ENV-006-*"))
