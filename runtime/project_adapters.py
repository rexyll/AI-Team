"""Deterministic language adapters for project build/test/package workflows.

Adapters describe commands; they never spawn processes directly. The executor
routes every command through ToolInvocationService's authorized run_command
boundary so role capabilities, workspace sandboxing and audit history remain
the source of truth.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol


ProjectAction = Literal["install", "build", "test", "package", "smoke", "deploy"]
PlanStatus = Literal["supported", "skipped", "unsupported"]
_ACTIONS: tuple[ProjectAction, ...] = (
    "install", "build", "test", "package", "smoke", "deploy",
)
_TEST_DIRS = frozenset({"node_modules", ".venv", "venv", ".git", "__pycache__"})


@dataclass(frozen=True)
class ProjectDetection:
    adapter: str
    language: str
    root: Path
    signals: tuple[str, ...]


@dataclass(frozen=True)
class ProjectCommand:
    command: str
    cwd: str = "."
    timeout_seconds: float = 600.0


@dataclass(frozen=True)
class ProjectActionPlan:
    adapter: str
    action: ProjectAction
    status: PlanStatus
    reason: str | None = None
    commands: tuple[ProjectCommand, ...] = ()


class ProjectAdapter(Protocol):
    name: str
    language: str

    def detect(self, root: Path) -> ProjectDetection | None: ...

    def plan(self, root: Path, action: ProjectAction) -> ProjectActionPlan: ...


def _root(path: str | Path) -> Path:
    candidate = Path(path).resolve()
    if not candidate.is_dir():
        raise NotADirectoryError(f"project root is not a directory: {candidate}")
    return candidate


def _python_tests(root: Path) -> bool:
    for path in root.rglob("*.py"):
        if any(part in _TEST_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name.startswith("test_") or path.name.endswith("_test.py"):
            return True
    return False


def _python_executable(root: Path) -> str:
    """Select the task-local interpreter when an isolated venv exists."""
    environment = root / ".venv"
    if environment.is_dir() and not environment.is_symlink():
        if os.name == "nt":
            return r".\\.venv\\Scripts\\python.exe"
        return "./.venv/bin/python"
    return "python"


def _node_package(root: Path) -> dict[str, object] | None:
    package_file = root / "package.json"
    if not package_file.is_file() or package_file.is_symlink():
        return None
    try:
        data = json.loads(package_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


class PythonProjectAdapter:
    name = "python"
    language = "python"

    def detect(self, root: Path) -> ProjectDetection | None:
        signals = tuple(
            name for name in ("pyproject.toml", "requirements.txt", "requirements-dev.txt", "setup.py", "setup.cfg")
            if (root / name).is_file() and not (root / name).is_symlink()
        )
        if not signals and not any(root.glob("*.py")):
            return None
        return ProjectDetection(self.name, self.language, root, signals or ("python-source",))

    def plan(self, root: Path, action: ProjectAction) -> ProjectActionPlan:
        root = _root(root)
        if action not in _ACTIONS:
            raise ValueError(f"unsupported project action: {action}")
        command: str | None = None
        commands: tuple[ProjectCommand, ...] = ()
        reason: str | None = None
        status: PlanStatus = "supported"
        has_project_metadata = (root / "pyproject.toml").is_file() or (root / "setup.py").is_file()
        has_requirements = (root / "requirements.txt").is_file()
        has_dev_requirements = (root / "requirements-dev.txt").is_file()
        if action == "install":
            if has_project_metadata or has_requirements or has_dev_requirements:
                install_commands = [ProjectCommand("python -m venv --system-site-packages .venv")]
                environment_python = (
                    r".\\.venv\\Scripts\\python.exe"
                    if os.name == "nt"
                    else "./.venv/bin/python"
                )
                if has_project_metadata:
                    requirements = " -r requirements.txt" if has_requirements else ""
                    install_commands.append(ProjectCommand(
                        f"{environment_python} -m pip install --disable-pip-version-check "
                        f"--no-build-isolation --cache-dir .ai-team-cache/pip -e .{requirements}"
                    ))
                elif has_requirements:
                    install_commands.append(ProjectCommand(
                        f"{environment_python} -m pip install --disable-pip-version-check --cache-dir .ai-team-cache/pip -r requirements.txt"
                    ))
                if has_dev_requirements:
                    install_commands.append(ProjectCommand(
                        f"{environment_python} -m pip install --disable-pip-version-check --cache-dir .ai-team-cache/pip -r requirements-dev.txt"
                    ))
                commands = tuple(install_commands)
            else:
                status, reason = "skipped", "no Python dependency manifest found"
        elif action == "build":
            python = _python_executable(root)
            if has_project_metadata:
                command = f"{python} -m build --no-isolation"
            else:
                command = f"{python} -m compileall -q ."
                reason = "source compilation check; no distributable build manifest found"
        elif action == "test":
            if _python_tests(root):
                command = f"{_python_executable(root)} -m pytest -q"
            else:
                status, reason = "skipped", "no Python test files found"
        elif action == "package":
            if has_project_metadata:
                command = f"{_python_executable(root)} -m build --no-isolation"
            else:
                status, reason = "unsupported", "Python package metadata is required for a distributable build"
        elif action == "smoke":
            python = _python_executable(root)
            command = f"{python} -m pytest -q" if _python_tests(root) else f"{python} -m compileall -q ."
            if not _python_tests(root):
                reason = "no tests found; smoke is limited to Python source compilation"
        else:
            status, reason = "unsupported", "deployment requires a configured deployment provider"
        if command is not None:
            commands = (ProjectCommand(command),)
        return ProjectActionPlan(self.name, action, status, reason, commands)


class NodeProjectAdapter:
    name = "node"
    language = "javascript"

    def detect(self, root: Path) -> ProjectDetection | None:
        package = _node_package(root)
        if package is None:
            return None
        signals = ["package.json"]
        for name in ("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock"):
            if (root / name).is_file() and not (root / name).is_symlink():
                signals.append(name)
        return ProjectDetection(self.name, self.language, root, tuple(signals))

    def plan(self, root: Path, action: ProjectAction) -> ProjectActionPlan:
        root = _root(root)
        if action not in _ACTIONS:
            raise ValueError(f"unsupported project action: {action}")
        package = _node_package(root)
        if package is None:
            return ProjectActionPlan(self.name, action, "unsupported", "valid package.json is required")
        scripts = package.get("scripts", {})
        if not isinstance(scripts, dict):
            scripts = {}
        command: str | None = None
        reason: str | None = None
        status: PlanStatus = "supported"
        has_npm_lock = any(
            (root / name).is_file() and not (root / name).is_symlink()
            for name in ("package-lock.json", "npm-shrinkwrap.json")
        )
        if action == "install":
            if has_npm_lock:
                command = "npm ci --ignore-scripts --no-audit --no-fund --cache .ai-team-cache/npm"
            else:
                status, reason = "unsupported", "npm lockfile is required for reproducible installation"
        elif action == "build":
            if isinstance(scripts.get("build"), str) and scripts["build"].strip():
                command = "npm run build"
            else:
                status, reason = "skipped", "package.json has no build script"
        elif action == "test":
            if isinstance(scripts.get("test"), str) and scripts["test"].strip():
                command = "npm test --if-present"
            else:
                status, reason = "skipped", "package.json has no test script"
        elif action == "package":
            command = "npm pack --ignore-scripts --json"
        elif action == "smoke":
            if isinstance(scripts.get("test"), str) and scripts["test"].strip():
                command = "npm test --if-present"
            else:
                status, reason = "skipped", "no test script is available for a Node.js smoke check"
        else:
            status, reason = "unsupported", "deployment requires a configured deployment provider"
        commands = (ProjectCommand(command),) if command else ()
        return ProjectActionPlan(self.name, action, status, reason, commands)


class ProjectAdapterRegistry:
    """Resolve language adapters independently from product/project categories."""

    def __init__(self, adapters: tuple[ProjectAdapter, ...] | None = None) -> None:
        selected = adapters if adapters is not None else (PythonProjectAdapter(), NodeProjectAdapter())
        names = [adapter.name for adapter in selected]
        if len(names) != len(set(names)):
            raise ValueError("project adapter names must be unique")
        self._adapters = {adapter.name: adapter for adapter in selected}

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def detect_all(self, root: str | Path) -> tuple[ProjectDetection, ...]:
        project_root = _root(root)
        found = [
            detection
            for adapter in self._adapters.values()
            if (detection := adapter.detect(project_root)) is not None
        ]
        return tuple(found)

    def resolve(self, root: str | Path, *, adapter_name: str | None = None) -> ProjectDetection:
        found = self.detect_all(root)
        if adapter_name is not None:
            adapter = self._adapters.get(adapter_name)
            if adapter is None:
                raise KeyError(f"unknown project adapter: {adapter_name}")
            detection = adapter.detect(_root(root))
            if detection is None:
                raise ValueError(f"project does not match adapter: {adapter_name}")
            return detection
        if not found:
            raise LookupError("no supported project adapter detected")
        if len(found) > 1:
            names = ", ".join(item.adapter for item in found)
            raise ValueError(f"multiple project adapters detected ({names}); select one explicitly")
        return found[0]

    def plan(
        self, root: str | Path, action: ProjectAction, *, adapter_name: str | None = None
    ) -> ProjectActionPlan:
        detection = self.resolve(root, adapter_name=adapter_name)
        return self._adapters[detection.adapter].plan(detection.root, action)


class ProjectAdapterExecutor:
    """Execute adapter plans only through the canonical tool invocation service."""

    _EXIT_CODE = re.compile(r"^exit_code=(-?\d+)\s*$", re.MULTILINE)

    def __init__(self, invocation_service) -> None:
        if not callable(getattr(invocation_service, "invoke", None)):
            raise TypeError("invocation_service must expose invoke()")
        self._invocation_service = invocation_service

    def execute(
        self,
        plan: ProjectActionPlan,
        *,
        role: str,
        task_id: str,
        execution_id: str,
    ) -> dict[str, object]:
        if plan.status != "supported":
            return {
                "status": plan.status,
                "adapter": plan.adapter,
                "action": plan.action,
                "reason": plan.reason,
                "steps": [],
            }
        steps: list[dict[str, object]] = []
        for index, command in enumerate(plan.commands, start=1):
            result = self._invocation_service.invoke(
                role=role,
                task_id=task_id,
                execution_id=f"{execution_id}-{index}",
                tool_name="run_command",
                arguments={
                    "command": command.command,
                    "cwd": command.cwd,
                    "timeout": command.timeout_seconds,
                },
            )
            if not result.success:
                steps.append({"success": False, "error": result.to_dict()["error"]})
                return {
                    "status": "failed",
                    "adapter": plan.adapter,
                    "action": plan.action,
                    "reason": "authorized command invocation failed",
                    "steps": steps,
                }
            output = str(result.output or "")
            match = self._EXIT_CODE.search(output)
            exit_code = int(match.group(1)) if match else None
            step_success = exit_code == 0
            steps.append({
                "success": step_success,
                "exit_code": exit_code,
                "output_tail": output[-2000:],
            })
            if not step_success:
                return {
                    "status": "failed",
                    "adapter": plan.adapter,
                    "action": plan.action,
                    "reason": "command returned a non-zero or unparseable exit code",
                    "steps": steps,
                }
        return {
            "status": "passed",
            "adapter": plan.adapter,
            "action": plan.action,
            "reason": plan.reason,
            "steps": steps,
        }


DEFAULT_PROJECT_ADAPTER_REGISTRY = ProjectAdapterRegistry()
