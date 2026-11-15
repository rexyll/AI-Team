from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from runtime.project_adapters import ProjectAdapterExecutor, ProjectAdapterRegistry
from runtime.tool_invocation_service import ToolInvocationService
from security.workspace import resolve_workspace_path, workspace_scope


def _write_e2e_evidence(project, *, tmp_path: Path, scenario: str, requirement: str) -> dict:
    from runtime.project_evidence_bundle import (
        validate_project_evidence_bundle,
        write_project_evidence_bundle,
    )

    output_dir = Path(
        os.environ.get("AI_TEAM_E2E_EVIDENCE_DIR", str(tmp_path / "evidence-artifacts"))
    )
    output = output_dir / f"{scenario}.evidence.json"
    record = write_project_evidence_bundle(
        project,
        requirement=requirement,
        deliverable_root=project.last_delivery["deliverable_root"],
        output_path=output,
        evidence_level="deterministic_orchestration",
        role_execution={
            "analyst": "not_registered",
            "planner": "scripted_test_double",
            "developer": "scripted_test_double",
            "tester": "scripted_test_double",
            "reviewer": "scripted_test_double",
            "doc_writer": "mock_llm",
            "qa": "not_registered",
            "security": "deterministic_gate",
            "sre": "deterministic_gate",
        },
        limitations=[
            "Planner/Developer/Tester/Reviewer use scripted role doubles; full LLM reasoning is not measured.",
            "Analyst and QA agent reasoning are not exercised in this scenario.",
            "Live ProviderLLM and external deployment are not run.",
        ],
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    validate_project_evidence_bundle(payload)
    assert record["sha256"] == payload["evidence_sha256"]
    assert payload["task_graph"]["workspace_isolation"]["status"] == "passed"
    assert payload["task_graph"]["workspace_isolation"]["leases_merged"] == 1
    assert payload["artifacts"]["manifest"]["status"] == "available"
    assert payload["artifacts"]["package"]["recorded_sha256_matches"] is True
    assert payload["tool_invocations"]
    return payload


@pytest.mark.skipif(
    os.name != "nt",
    reason="production Node.js adapter E2E runs on the Windows toolchain CI job",
)
def test_node_web_adapter_executes_real_npm_lifecycle_through_tool_boundary(
    tmp_path: Path,
) -> None:
    package = {
        "name": "ai-team-node-web-e2e",
        "version": "1.0.0",
        "private": True,
        "type": "commonjs",
        "scripts": {
            "build": "node scripts/build.js",
            "test": "node --test",
        },
    }
    (tmp_path / "package.json").write_text(
        json.dumps(package, indent=2) + "\n",
        encoding="utf-8",
    )
    lock = {
        "name": package["name"],
        "version": package["version"],
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": {
                "name": package["name"],
                "version": package["version"],
            }
        },
    }
    (tmp_path / "package-lock.json").write_text(
        json.dumps(lock, indent=2) + "\n",
        encoding="utf-8",
    )

    source = tmp_path / "src"
    source.mkdir()
    (source / "index.html").write_text(
        "<!doctype html><html><body><main id=\"app\">AI-Team E2E</main></body></html>\n",
        encoding="utf-8",
    )
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "build.js").write_text(
        "const fs = require('node:fs');\n"
        "const path = require('node:path');\n"
        "const root = process.cwd();\n"
        "fs.mkdirSync(path.join(root, 'dist'), { recursive: true });\n"
        "fs.copyFileSync(path.join(root, 'src', 'index.html'), "
        "path.join(root, 'dist', 'index.html'));\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "app.test.js").write_text(
        "const test = require('node:test');\n"
        "const assert = require('node:assert/strict');\n"
        "const fs = require('node:fs');\n"
        "const path = require('node:path');\n"
        "test('built web entry contains the application marker', () => {\n"
        "  const html = fs.readFileSync(path.join(process.cwd(), 'dist', 'index.html'), 'utf8');\n"
        "  assert.ok(html.includes('AI-Team E2E'));\n"
        "});\n",
        encoding="utf-8",
    )

    registry = ProjectAdapterRegistry()
    detection = registry.resolve(tmp_path, adapter_name="node")
    assert detection.adapter == "node"
    assert "package-lock.json" in detection.signals

    service = ToolInvocationService()
    executor = ProjectAdapterExecutor(service)
    with workspace_scope(tmp_path):
        for action in ("install", "build", "test", "smoke", "package"):
            plan = registry.plan(tmp_path, action, adapter_name="node")
            assert plan.status == "supported", (action, plan)
            result = executor.execute(
                plan,
                role="developer",
                task_id=f"NODE-WEB-E2E-{action.upper()}",
                execution_id=f"NODE-WEB-E2E-EXEC-{action.upper()}",
            )
            assert result["status"] == "passed", (action, result)

        # The built artifact is inspected after build/test/smoke/package.
        built_entry = tmp_path / "dist" / "index.html"
        assert built_entry.is_file()
        assert "AI-Team E2E" in built_entry.read_text(encoding="utf-8")
        assert (tmp_path / "node_modules").is_dir()

        deploy = registry.plan(tmp_path, "deploy", adapter_name="node")
        assert deploy.status == "unsupported"
        assert "deployment provider" in (deploy.reason or "")

    records = service.audit.records()
    assert len(records) == 5
    assert all(record.status == "completed" for record in records)
    assert all(record.agent_role == "developer" for record in records)
    assert all(record.tool_name == "run_command" for record in records)



class _E2EPlanner:
    role = "planner"

    def run(self, task):
        return {
            "status": "completed",
            "agent": "planner",
            "task_id": task.id,
            "plan": {
                "project": "node-web-orchestrator-e2e",
                "summary": "Deterministic Node.js Web delivery through ProjectOrchestrator",
                "tasks": [{
                    "id": "TASK-NODE-WEB-001",
                    "title": "Implement the Node.js Web application",
                    "description": "Create a static web entry, deterministic build and executable test.",
                    "role": "developer",
                    "dependencies": [],
                }],
            },
        }


class _E2EDeveloper:
    role = "developer"

    def run(self, task):
        # DeveloperWorkspaceManager activates a task-local lease as the workspace scope.
        # Resolve the current workspace instead of writing to the canonical project root.
        root = resolve_workspace_path(".")
        (root / "src").mkdir(parents=True, exist_ok=True)
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        (root / "tests").mkdir(parents=True, exist_ok=True)
        package = {
            "name": "ai-team-orchestrator-web-e2e",
            "version": "1.0.0",
            "private": True,
            "type": "commonjs",
            "scripts": {"build": "node scripts/build.js", "test": "node --test"},
        }
        (root / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
        lock = {
            "name": package["name"],
            "version": package["version"],
            "lockfileVersion": 3,
            "requires": True,
            "packages": {"": {"name": package["name"], "version": package["version"]}},
        }
        (root / "package-lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        (root / "src" / "index.html").write_text(
            "<!doctype html><html><body><main>ORCHESTRATOR-WEB-DELIVERABLE</main></body></html>\n",
            encoding="utf-8",
        )
        (root / "scripts" / "build.js").write_text(
            "const fs = require('node:fs');\n"
            "const path = require('node:path');\n"
            "fs.mkdirSync('dist', { recursive: true });\n"
            "fs.copyFileSync(path.join('src', 'index.html'), path.join('dist', 'index.html'));\n",
            encoding="utf-8",
        )
        (root / "tests" / "app.test.js").write_text(
            "const test = require('node:test');\n"
            "const assert = require('node:assert/strict');\n"
            "const fs = require('node:fs');\n"
            "test('built application contains its acceptance marker', () => {\n"
            "  const html = fs.readFileSync('dist/index.html', 'utf8');\n"
            "  assert.ok(html.includes('ORCHESTRATOR-WEB-DELIVERABLE'));\n"
            "});\n",
            encoding="utf-8",
        )
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "Created the locked Node.js Web fixture and executable acceptance test.",
        }


class _E2ETester:
    role = "tester"

    def run(self, task):
        return {
            "status": "passed",
            "agent": "tester",
            "task_id": task.id,
            "message": "TEST_PASSED: deterministic developer output accepted for integration execution.",
        }


class _E2EReviewer:
    role = "reviewer"

    def run(self, task):
        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "message": "APPROVED: implementation evidence is ready for integration gates.",
        }


@pytest.mark.skipif(
    os.name != "nt",
    reason="full production ProjectOrchestrator + npm E2E runs on Windows toolchain CI",
)
def test_node_web_requirement_runs_through_project_orchestrator_and_delivery(
    monkeypatch, tmp_path: Path
) -> None:
    from agents.doc_writer import DocWriterAgent
    from core.project_orchestrator import ProjectOrchestrator
    from runtime.agent_config import AgentConfig
    from runtime.agent_router import AgentRouter
    from runtime.llm.mock import MockLLM
    from security.workspace import WorkspaceSandbox

    monkeypatch.setenv("AI_TEAM_PROJECT_ADAPTERS", "1")
    monkeypatch.setenv("AI_TEAM_PROJECT_ADAPTER", "node")
    monkeypatch.setenv("AI_TEAM_STATIC_GATE", "0")
    monkeypatch.setenv("AI_TEAM_INTEGRATION_MAX_ROUNDS", "0")

    sandbox = WorkspaceSandbox(tmp_path)
    router = AgentRouter()
    for role, agent in (
        ("planner", _E2EPlanner()),
        ("developer", _E2EDeveloper()),
        ("tester", _E2ETester()),
        ("reviewer", _E2EReviewer()),
        (
            "doc_writer",
            DocWriterAgent(
                AgentConfig(role="doc_writer", model="deterministic-mock"),
                llm=MockLLM("# Deterministic project delivery documentation\n"),
                sandbox=sandbox,
            ),
        ),
    ):
        router.register(role, agent)

    project = ProjectOrchestrator(
        agent_router=router,
        project_id="T21-8-NODE-WEB-E2E",
        deliverable_dir="webapp",
        sandbox=sandbox,
    )
    result = project.run(
        "Create a small Node.js Web project with a reproducible npm lockfile, "
        "a deterministic build, an executable test, and a packaged deliverable. "
        "Do not deploy or publish it."
    )

    assert result.success, result
    assert result.total_tasks == 1
    assert result.completed_tasks == 1
    task = project.last_task_manager.get_all_tasks()[0]
    assert "package.json" in task.context["workspace_merge"]["added"]
    assert "src/index.html" in task.context["workspace_merge"]["added"]
    assert project.last_delivery is not None
    integration = project.last_delivery["integration"]
    assert integration["status"] in {"passed", "skipped"}
    adapter = integration["adapter"]
    assert adapter["status"] == "passed", adapter
    assert adapter["adapter"] == "node"
    assert set(adapter["actions"]) == {"install", "build", "test", "smoke", "package"}
    assert all(item["status"] == "passed" for item in adapter["actions"].values())
    assert all(
        item["tool_name"] == "run_command"
        for item in adapter["tool_execution_history"]
    )

    root = tmp_path / "webapp"
    built_entry = root / "dist" / "index.html"
    assert built_entry.is_file()
    assert "ORCHESTRATOR-WEB-DELIVERABLE" in built_entry.read_text(encoding="utf-8")
    assert (root / "node_modules").is_dir()
    assert Path(project.last_delivery["manifest"]).is_file()
    package = project.last_delivery["package"]
    assert package["archive"]
    assert Path(package["archive"]).is_file()
    assert project.last_delivery["security"]["verdict"] == "SEC_PASSED"
    lease = task.context["workspace_lease"]
    assert lease["lease_id"]
    assert lease["disposition"] == "merged"
    evidence = _write_e2e_evidence(
        project,
        tmp_path=tmp_path,
        scenario="node-web",
        requirement=(
            "Create a small Node.js Web project with a reproducible npm lockfile, "
            "a deterministic build, an executable test, and a packaged deliverable. "
            "Do not deploy or publish it."
        ),
    )
    assert evidence["project_profile"]["project_type"] == "web"
    assert evidence["gates"]["security"]["verdict"] == "SEC_PASSED"



class _PythonE2EPlanner:
    role = "planner"

    def run(self, task):
        return {
            "status": "completed",
            "agent": "planner",
            "task_id": task.id,
            "plan": {
                "project": "python-cli-orchestrator-e2e",
                "summary": "Deterministic Python CLI delivery through ProjectOrchestrator",
                "tasks": [{
                    "id": "TASK-PYTHON-CLI-001",
                    "title": "Implement the Python CLI application",
                    "description": "Create an installable CLI package with executable tests.",
                    "role": "developer",
                    "dependencies": [],
                }],
            },
        }


class _PythonE2EDeveloper:
    role = "developer"

    def run(self, task):
        # The production Orchestrator activates a task lease as workspace scope.
        root = resolve_workspace_path(".")
        package = root / "sample_app"
        package.mkdir(parents=True, exist_ok=True)
        tests = root / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        (root / "pyproject.toml").write_text(
            "[build-system]\nrequires = ['setuptools>=75']\n"
            "build-backend = 'setuptools.build_meta'\n"
            "[project]\nname = 'ai-team-orchestrator-cli-e2e'\n"
            "version = '0.1.0'\nrequires-python = '>=3.10'\n"
            "[project.scripts]\nsample-cli = 'sample_app.cli:main'\n"
            "[tool.setuptools.packages.find]\nwhere = ['.']\n",
            encoding="utf-8",
        )
        (root / "requirements.txt").write_text("", encoding="utf-8")
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
        (tests / "test_cli.py").write_text(
            "import subprocess\nimport sys\n\n"
            "def test_cli_success_and_invalid_input():\n"
            "    ok = subprocess.run([sys.executable, '-m', 'sample_app.cli', '--value', '21'], "
            "capture_output=True, text=True, check=False)\n"
            "    assert ok.returncode == 0\n"
            "    assert ok.stdout.strip() == '42'\n"
            "    bad = subprocess.run([sys.executable, '-m', 'sample_app.cli', '--value', 'nope'], "
            "capture_output=True, text=True, check=False)\n"
            "    assert bad.returncode != 0\n",
            encoding="utf-8",
        )
        (root / "README.md").write_text(
            "# Sample CLI\n\nInstall with pip install -e . and run "
            "sample-cli --value 21; expected output: 42.\n",
            encoding="utf-8",
        )
        return {
            "status": "completed",
            "agent": "developer",
            "task_id": task.id,
            "message": "Created the installable Python CLI package and executable tests.",
        }


@pytest.mark.skipif(
    os.name != "nt",
    reason="full production ProjectOrchestrator + Python CLI E2E runs on Windows toolchain CI",
)
def test_python_cli_requirement_runs_through_project_orchestrator_and_delivery(
    monkeypatch, tmp_path: Path
) -> None:
    import subprocess

    from agents.doc_writer import DocWriterAgent
    from core.project_orchestrator import ProjectOrchestrator
    from runtime.agent_config import AgentConfig
    from runtime.agent_router import AgentRouter
    from runtime.llm.mock import MockLLM
    from security.workspace import WorkspaceSandbox

    monkeypatch.setenv("AI_TEAM_PROJECT_ADAPTERS", "1")
    monkeypatch.setenv("AI_TEAM_PROJECT_ADAPTER", "python")
    monkeypatch.setenv("AI_TEAM_STATIC_GATE", "0")
    monkeypatch.setenv("AI_TEAM_INTEGRATION_MAX_ROUNDS", "0")

    sandbox = WorkspaceSandbox(tmp_path)
    router = AgentRouter()
    for role, agent in (
        ("planner", _PythonE2EPlanner()),
        ("developer", _PythonE2EDeveloper()),
        ("tester", _E2ETester()),
        ("reviewer", _E2EReviewer()),
        (
            "doc_writer",
            DocWriterAgent(
                AgentConfig(role="doc_writer", model="deterministic-mock"),
                llm=MockLLM("# Deterministic Python CLI delivery documentation\n"),
                sandbox=sandbox,
            ),
        ),
    ):
        router.register(role, agent)

    project = ProjectOrchestrator(
        agent_router=router,
        project_id="T21-8-PYTHON-CLI-E2E",
        deliverable_dir="cli",
        sandbox=sandbox,
    )
    result = project.run(
        "Create an installable Python CLI package with reproducible setup, "
        "a documented command, tests for valid and invalid input, and a package. "
        "Do not publish or deploy it."
    )

    assert result.success, result
    assert result.total_tasks == 1
    assert result.completed_tasks == 1
    task = project.last_task_manager.get_all_tasks()[0]
    assert "pyproject.toml" in task.context["workspace_merge"]["added"]
    assert "sample_app/cli.py" in task.context["workspace_merge"]["added"]
    assert project.last_delivery is not None
    integration = project.last_delivery["integration"]
    assert integration["status"] in {"passed", "skipped"}
    adapter = integration["adapter"]
    assert adapter["status"] == "passed", adapter
    assert adapter["adapter"] == "python"
    assert set(adapter["actions"]) == {"install", "build", "test", "smoke", "package"}
    assert all(item["status"] == "passed" for item in adapter["actions"].values())
    assert all(
        item["tool_name"] == "run_command"
        for item in adapter["tool_execution_history"]
    )

    root = tmp_path / "cli"
    executable = root / ".venv" / "Scripts" / "sample-cli.exe"
    assert executable.is_file()
    completed = subprocess.run(
        [str(executable), "--value", "21"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "42"
    assert Path(project.last_delivery["manifest"]).is_file()
    package = project.last_delivery["package"]
    assert package["archive"]
    assert Path(package["archive"]).is_file()
    assert project.last_delivery["security"]["verdict"] == "SEC_PASSED"
    lease = task.context["workspace_lease"]
    assert lease["lease_id"]
    assert lease["disposition"] == "merged"
    evidence = _write_e2e_evidence(
        project,
        tmp_path=tmp_path,
        scenario="python-cli",
        requirement=(
            "Create an installable Python CLI package with reproducible setup, "
            "a documented command, tests for valid and invalid input, and a package. "
            "Do not publish or deploy it."
        ),
    )
    assert evidence["project_profile"]["project_type"] == "cli"
    assert evidence["gates"]["security"]["verdict"] == "SEC_PASSED"
