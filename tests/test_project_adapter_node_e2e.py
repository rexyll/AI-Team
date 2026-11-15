from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from runtime.project_adapters import ProjectAdapterExecutor, ProjectAdapterRegistry
from runtime.tool_invocation_service import ToolInvocationService
from security.workspace import workspace_scope


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
