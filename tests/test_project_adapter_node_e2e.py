from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from runtime.project_adapters import ProjectAdapterExecutor, ProjectAdapterRegistry
from runtime.tool_invocation_service import ToolInvocationService
from security.workspace import resolve_workspace_path, workspace_scope


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
