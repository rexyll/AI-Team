from __future__ import annotations

import os
from pathlib import Path

import pytest

from runtime.project_adapters import ProjectAdapterExecutor, ProjectAdapterRegistry
from runtime.tool_invocation_service import ToolInvocationService
from security.workspace import workspace_scope


@pytest.mark.skipif(os.name != "nt", reason="production terminal smoke runs on Windows CI")
def test_python_adapter_uses_production_windows_run_command(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[build-system]\\nrequires = ['setuptools>=75']\\nbuild-backend = 'setuptools.build_meta'\\n"
        "[project]\\nname = 'windows-adapter-fixture'\\nversion = '0.1.0'\\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    (tmp_path / "sample.py").write_text("VALUE = 42\\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_sample.py").write_text(
        "from sample import VALUE\n\ndef test_value():\n    assert VALUE == 42\n",
        encoding="utf-8",
    )

    registry = ProjectAdapterRegistry()
    service = ToolInvocationService()
    executor = ProjectAdapterExecutor(service)

    with workspace_scope(tmp_path):
        for action in ("install", "build", "test", "smoke", "package"):
            plan = registry.plan(tmp_path, action, adapter_name="python")
            result = executor.execute(
                plan,
                role="developer",
                task_id=f"WINDOWS-ADAPTER-{action}",
                execution_id=f"WINDOWS-ADAPTER-EXEC-{action}",
            )
            assert result["status"] == "passed", (action, result)

        # A deliberately broken source file must surface a non-zero
        # native process exit code through PowerShell and the tool boundary.
        (tmp_path / "broken.py").write_text("def broken(:", encoding="utf-8")
        (tests / "test_broken.py").write_text(
            "import broken\\n\\ndef test_broken():\\n    assert broken.VALUE == 1\\n",
            encoding="utf-8",
        )
        failed_test = executor.execute(
            registry.plan(tmp_path, "test", adapter_name="python"),
            role="developer",
            task_id="WINDOWS-ADAPTER-TEST-FAIL",
            execution_id="WINDOWS-ADAPTER-EXEC-TEST-FAIL",
        )
        assert failed_test["status"] == "failed", failed_test

    records = service.audit.records()
    assert len(records) == 7
    assert all(record.status == "completed" for record in records)
    assert all(record.agent_role == "developer" for record in records)
