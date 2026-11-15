from __future__ import annotations

import os
from pathlib import Path

import pytest

from runtime.project_adapters import ProjectAdapterExecutor, ProjectAdapterRegistry
from runtime.tool_invocation_service import ToolInvocationService
from security.workspace import workspace_scope


@pytest.mark.skipif(os.name != "nt", reason="production terminal smoke runs on Windows CI")
def test_python_cli_adapter_uses_production_run_command_and_executes_deliverable(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[build-system]\nrequires = ['setuptools>=75']\nbuild-backend = 'setuptools.build_meta'\n"
        "[project]\nname = 'windows-adapter-fixture'\nversion = '0.1.0'\n"
        "[project.scripts]\nsample-cli = 'sample_app.cli:main'\n"
        "[tool.setuptools.packages.find]\nwhere = ['.']\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    package = tmp_path / "sample_app"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text(
        "import argparse\n\n"
        "def main():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--value', type=int, required=True)\n"
        "    args = parser.parse_args()\n"
        "    print(args.value * 2)\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_cli.py").write_text(
        "import subprocess\nimport sys\n\n"
        "def test_cli_success_and_invalid_input():\n"
        "    ok = subprocess.run([sys.executable, '-m', 'sample_app.cli', '--value', '21'], "
        "capture_output=True, text=True, check=False)\n"
        "    assert ok.returncode == 0\n"
        "    assert ok.stdout.strip() == '42'\n"
        "    bad = subprocess.run([sys.executable, '-m', 'sample_app.cli', '--value', 'not-int'], "
        "capture_output=True, text=True, check=False)\n"
        "    assert bad.returncode != 0\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "# Sample CLI\n\nInstall with `pip install -e .` and run "
        "`sample-cli --value 21`; expected output: `42`.\n",
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
                task_id=f"WINDOWS-CLI-ADAPTER-{action}",
                execution_id=f"WINDOWS-CLI-ADAPTER-EXEC-{action}",
            )
            assert result["status"] == "passed", (action, result)

        # Execute the installed console script from the isolated project venv.
        cli = tmp_path / ".venv" / "Scripts" / "sample-cli.exe"
        assert cli.is_file()
        import subprocess

        run = subprocess.run(
            [str(cli), "--value", "21"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert run.returncode == 0, run.stderr
        assert run.stdout.strip() == "42"

        # A deliberately broken source file must surface a non-zero process
        # exit code through PowerShell and the production tool boundary.
        (tmp_path / "broken.py").write_text("def broken(:", encoding="utf-8")
        (tests / "test_broken.py").write_text(
            "import broken\n\ndef test_broken():\n    assert broken.VALUE == 1\n",
            encoding="utf-8",
        )
        failed_test = executor.execute(
            registry.plan(tmp_path, "test", adapter_name="python"),
            role="developer",
            task_id="WINDOWS-CLI-ADAPTER-TEST-FAIL",
            execution_id="WINDOWS-CLI-ADAPTER-EXEC-TEST-FAIL",
        )
        assert failed_test["status"] == "failed", failed_test

    records = service.audit.records()
    assert len(records) == 7
    assert all(record.status == "completed" for record in records)
    assert all(record.agent_role == "developer" for record in records)
    assert all(record.tool_name == "run_command" for record in records)
