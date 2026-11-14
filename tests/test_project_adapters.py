from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from runtime.project_adapters import (
    NodeProjectAdapter,
    ProjectActionPlan,
    ProjectAdapterExecutor,
    ProjectAdapterRegistry,
    ProjectCommand,
    PythonProjectAdapter,
)
from runtime.tool_result import ToolResult
from runtime.tool_invocation_service import ToolInvocationService
from tools.registry import ToolRegistry
from security.workspace import WorkspaceSandbox



def _real_tool_service_for_fixture(root: Path) -> ToolInvocationService:
    sandbox = WorkspaceSandbox(root)

    def run_command(command: str, cwd: str = ".", timeout: float = 600.0) -> str:
        completed = subprocess.run(
            shlex.split(command),
            cwd=sandbox.resolve(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        output = completed.stdout
        if completed.stderr:
            output += "\n" + completed.stderr
        return f"exit_code={completed.returncode}\n{output}"

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
    return ToolInvocationService(registry=registry)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_python_adapter_detects_manifest_and_plans_supported_actions(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", "[project]\nname='demo'\nversion='0.1.0'\n")
    _write(tmp_path / "requirements-dev.txt", "pytest\n")
    _write(tmp_path / "tests" / "test_demo.py", "def test_ok(): assert True\n")
    registry = ProjectAdapterRegistry()

    detection = registry.resolve(tmp_path)
    install = registry.plan(tmp_path, "install")
    build = registry.plan(tmp_path, "build")
    test = registry.plan(tmp_path, "test")
    package = registry.plan(tmp_path, "package")
    deploy = registry.plan(tmp_path, "deploy")

    assert detection.adapter == "python"
    assert detection.language == "python"
    assert install.commands[0].command == "python -m venv --system-site-packages .venv"
    assert ".ai-team-cache/pip" in install.commands[1].command
    assert install.commands[1].command.endswith(
        " -m pip install --disable-pip-version-check --no-build-isolation "
        "--cache-dir .ai-team-cache/pip -e ."
    )
    assert install.commands[2].command.endswith(
        "--cache-dir .ai-team-cache/pip -r requirements-dev.txt"
    )
    assert build.commands[0].command == "python -m build --no-isolation"
    assert test.commands[0].command == "python -m pytest -q"
    assert package.status == "supported"
    assert deploy.status == "unsupported"


def test_python_adapter_reports_missing_tests_as_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "requirements.txt", "pytest\n")

    plan = PythonProjectAdapter().plan(tmp_path, "test")

    assert plan.status == "skipped"
    assert not plan.commands


def test_node_adapter_requires_valid_package_and_npm_lock_for_install(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", json.dumps({"name": "demo", "scripts": {"build": "vite build", "test": "vitest run"}}))
    adapter = NodeProjectAdapter()

    detection = adapter.detect(tmp_path)
    install_without_lock = adapter.plan(tmp_path, "install")
    build = adapter.plan(tmp_path, "build")
    test = adapter.plan(tmp_path, "test")
    package = adapter.plan(tmp_path, "package")
    smoke = adapter.plan(tmp_path, "smoke")

    assert detection is not None
    assert detection.adapter == "node"
    assert install_without_lock.status == "unsupported"
    assert build.commands[0].command == "npm run build"
    assert test.commands[0].command == "npm test --if-present"
    assert package.commands[0].command == "npm pack --ignore-scripts --json"
    assert smoke.commands[0].command == "npm test --if-present"

    _write(tmp_path / "package-lock.json", "{}")
    install = adapter.plan(tmp_path, "install")
    assert install.commands[0].command == "npm ci --ignore-scripts --no-audit --no-fund --cache node_modules/.cache/npm"


def test_node_adapter_reports_missing_scripts_as_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", json.dumps({"name": "empty"}))

    plan = NodeProjectAdapter().plan(tmp_path, "build")

    assert plan.status == "skipped"
    assert not plan.commands


def test_registry_rejects_unknown_and_ambiguous_projects(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "no supported language marker")

    with pytest.raises(LookupError, match="no supported project adapter"):
        ProjectAdapterRegistry().resolve(tmp_path)

    _write(tmp_path / "main.py", "print('hello')")
    _write(tmp_path / "package.json", json.dumps({"name": "polyglot"}))
    with pytest.raises(ValueError, match="multiple project adapters"):
        ProjectAdapterRegistry().resolve(tmp_path)

    assert ProjectAdapterRegistry().resolve(tmp_path, adapter_name="python").adapter == "python"


def test_registry_rejects_invalid_root_and_unknown_adapter(tmp_path: Path) -> None:
    registry = ProjectAdapterRegistry()

    with pytest.raises(NotADirectoryError):
        registry.detect_all(tmp_path / "missing")
    with pytest.raises(KeyError, match="unknown project adapter"):
        registry.resolve(tmp_path, adapter_name="rust")



def test_python_fixture_executes_install_build_test_package_and_smoke_through_tool_service(tmp_path: Path) -> None:
    if not shutil.which("python"):
        pytest.skip("python executable is unavailable")
    _write(
        tmp_path / "pyproject.toml",
        "[build-system]\nrequires = ['setuptools>=75']\nbuild-backend = 'setuptools.build_meta'\n"
        "[project]\nname = 'ai-team-python-fixture'\nversion = '0.1.0'\n",
    )
    _write(tmp_path / "requirements.txt", "")
    _write(tmp_path / "fixture_pkg" / "__init__.py", "VALUE = 42\n")
    _write(
        tmp_path / "tests" / "test_fixture.py",
        "from fixture_pkg import VALUE\n\ndef test_value():\n    assert VALUE == 42\n",
    )
    executor = ProjectAdapterExecutor(_real_tool_service_for_fixture(tmp_path))
    registry = ProjectAdapterRegistry()

    for action in ("install", "build", "test", "package", "smoke"):
        result = executor.execute(
            registry.plan(tmp_path, action, adapter_name="python"),
            role="developer",
            task_id=f"PY-{action}",
            execution_id=f"PY-EXEC-{action}",
        )
        assert result["status"] == "passed", (action, result)

    assert list((tmp_path / "dist").glob("*.whl"))
    assert list((tmp_path / "dist").glob("*.tar.gz"))


def test_node_fixture_executes_install_build_test_package_and_smoke_through_tool_service(tmp_path: Path) -> None:
    if not shutil.which("node") or not shutil.which("npm"):
        pytest.skip("Node.js/npm are unavailable")
    package = {
        "name": "ai-team-node-fixture",
        "version": "1.0.0",
        "private": True,
        "scripts": {"build": "node build.js", "test": "node test.js"},
    }
    _write(tmp_path / "package.json", json.dumps(package))
    _write(
        tmp_path / "package-lock.json",
        json.dumps({
            "name": package["name"],
            "version": package["version"],
            "lockfileVersion": 3,
            "requires": True,
            "packages": {"": {"name": package["name"], "version": package["version"]}},
        }),
    )
    _write(
        tmp_path / "build.js",
        "const fs = require('fs'); fs.mkdirSync('dist', {recursive:true}); fs.writeFileSync('dist/result.txt', 'built');\n",
    )
    _write(
        tmp_path / "test.js",
        "const fs = require('fs'); if (fs.readFileSync('dist/result.txt', 'utf8') !== 'built') process.exit(1);\n",
    )
    executor = ProjectAdapterExecutor(_real_tool_service_for_fixture(tmp_path))
    registry = ProjectAdapterRegistry()

    for action in ("install", "build", "test", "package", "smoke"):
        result = executor.execute(
            registry.plan(tmp_path, action, adapter_name="node"),
            role="developer",
            task_id=f"NODE-{action}",
            execution_id=f"NODE-EXEC-{action}",
        )
        assert result["status"] == "passed", (action, result)

    assert (tmp_path / "dist" / "result.txt").read_text(encoding="utf-8") == "built"
    assert list(tmp_path.glob("*.tgz"))


def test_adapter_executor_routes_commands_through_tool_invocation_service() -> None:
    class _InvocationService:
        def __init__(self) -> None:
            self.calls = []

        def invoke(self, **kwargs):
            self.calls.append(kwargs)
            return ToolResult.ok("exit_code=0\nBuild completed")

    service = _InvocationService()
    executor = ProjectAdapterExecutor(service)
    plan = ProjectActionPlan(
        adapter="python",
        action="build",
        status="supported",
        commands=(ProjectCommand("python -m compileall -q .", timeout_seconds=90),),
    )

    result = executor.execute(
        plan,
        role="developer",
        task_id="TASK-001",
        execution_id="EXEC-001",
    )

    assert result["status"] == "passed"
    assert service.calls == [{
        "role": "developer",
        "task_id": "TASK-001",
        "execution_id": "EXEC-001-1",
        "tool_name": "run_command",
        "arguments": {
            "command": "python -m compileall -q .",
            "cwd": ".",
            "timeout": 90,
        },
    }]


def test_adapter_executor_fails_on_nonzero_or_missing_exit_code() -> None:
    class _InvocationService:
        def __init__(self, output: str) -> None:
            self.output = output

        def invoke(self, **kwargs):
            return ToolResult.ok(self.output)

    plan = ProjectActionPlan(
        adapter="node",
        action="build",
        status="supported",
        commands=(ProjectCommand("npm run build"),),
    )
    for output in ("exit_code=2\ncompile failed", "command finished without exit marker"):
        result = ProjectAdapterExecutor(_InvocationService(output)).execute(
            plan, role="developer", task_id="TASK-002", execution_id="EXEC-002"
        )
        assert result["status"] == "failed"


def test_adapter_executor_does_not_invoke_skipped_or_unsupported_plans() -> None:
    class _InvocationService:
        def invoke(self, **kwargs):
            raise AssertionError("unsupported plans must never execute")

    executor = ProjectAdapterExecutor(_InvocationService())
    for status in ("skipped", "unsupported"):
        plan = ProjectActionPlan(
            adapter="node",
            action="deploy",
            status=status,
            reason="provider is not configured",
        )
        result = executor.execute(
            plan, role="developer", task_id="TASK-003", execution_id="EXEC-003"
        )
        assert result["status"] == status
        assert result["steps"] == []


def test_adapter_executor_reports_tool_boundary_denials() -> None:
    class _InvocationService:
        def invoke(self, **kwargs):
            return ToolResult.from_exception(PermissionError("not authorized"))

    plan = ProjectActionPlan(
        adapter="python",
        action="test",
        status="supported",
        commands=(ProjectCommand("python -m pytest -q"),),
    )
    result = ProjectAdapterExecutor(_InvocationService()).execute(
        plan, role="tester", task_id="TASK-004", execution_id="EXEC-004"
    )

    assert result["status"] == "failed"
    assert result["steps"][0]["success"] is False
