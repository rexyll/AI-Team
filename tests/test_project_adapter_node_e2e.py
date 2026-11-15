from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from runtime.llm.base import LLMResponse
from runtime.llm.mock import MockLLM
from runtime.project_adapters import ProjectAdapterExecutor, ProjectAdapterRegistry
from runtime.tool_invocation_service import ToolInvocationService
from security.workspace import resolve_workspace_path, workspace_scope


def _write_e2e_evidence(
    project,
    *,
    tmp_path: Path,
    scenario: str,
    requirement: str,
    role_execution: dict[str, str] | None = None,
) -> dict:
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
        role_execution=role_execution or {
            "analyst": "not_registered",
            "planner": "production_planner_agent_mock_llm",
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
            "Analyst/QA, when registered, use deterministic MockLLM responses and do not measure live provider reasoning.",
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
    qa_invocations = [
        item for item in payload["tool_invocations"] if item["role"] == "qa"
    ]
    assert len(qa_invocations) == 3
    assert all(item["status"] == "completed" for item in qa_invocations)
    assert payload["gates"]["qa"]["tool_invocation_count"] == 3
    assert payload["gates"]["acceptance"]["verdict"] == "passed"
    assert payload["gates"]["acceptance"]["executable_verdict"] == "passed"
    assert payload["tool_invocations"]
    return payload


@pytest.mark.skipif(
    os.name != "nt",
    reason="DeveloperAgent run_command uses the Windows PowerShell execution boundary",
)
def test_production_developer_tester_reviewer_pipeline_uses_real_execution_evidence(
    tmp_path: Path,
) -> None:
    """Exercise real role agents and evidence lineage around an actual pytest run."""
    from agents.developer import DeveloperAgent
    from agents.reviewer import ReviewerAgent
    from agents.tester import TesterAgent
    from runtime.agent_config import AgentConfig
    from runtime.agent_router import AgentRouter
    from runtime.task import Task
    from runtime.task_manager import TaskManager
    from runtime.workflow import TaskWorkflow
    from runtime.provenance import provenance_from_value

    task = Task(
        id="TASK-PRODUCTION-AGENT-PIPELINE-001",
        title="Implement and verify a small calculator module",
        description=(
            "Create calculator.py with an add function, create pytest coverage "
            "for positive and negative values, and run the exact test command."
        ),
        role="developer",
    )
    developer_llm = MockLLM(
        tool_script=[
            {
                "tool_calls": [
                    {
                        "call_id": "developer-write-module",
                        "name": "write_file",
                        "arguments": json.dumps(
                            {
                                "path": "calculator.py",
                                "content": (
                                    "def add(left: int, right: int) -> int:\n"
                                    "    return left + right\n"
                                ),
                            }
                        ),
                    },
                    {
                        "call_id": "developer-write-tests",
                        "name": "write_file",
                        "arguments": json.dumps(
                            {
                                "path": "tests/test_calculator.py",
                                "content": (
                                    "from calculator import add\n\n"
                                    "def test_add_positive_values():\n"
                                    "    assert add(20, 22) == 42\n\n"
                                    "def test_add_negative_values():\n"
                                    "    assert add(-1, 1) == 0\n"
                                ),
                            }
                        ),
                    },
                ]
            },
            {
                "tool_calls": [
                    {
                        "call_id": "developer-run-pytest",
                        "name": "run_command",
                        "arguments": json.dumps(
                            {
                                "command": "python -m pytest -q tests/test_calculator.py",
                                "cwd": ".",
                                "timeout": 90,
                            }
                        ),
                    }
                ]
            },
        ]
    )
    class _EvidenceAwareTesterLLM(MockLLM):
        def __init__(self) -> None:
            super().__init__()
            self.evidence_accepted = False

        def generate(
            self,
            prompt: str,
            *,
            system_prompt: str = "",
            temperature: float = 0.2,
            max_tokens: int = 4096,
        ) -> str:
            self.evidence_accepted = (
                "exit_code=0" in prompt
                and "2 passed" in prompt
                and "test_calculator.py" in prompt
            )
            self.response = (
                "TEST_PASSED\n实际 pytest 结果为 2 passed，退出码为 0。"
                if self.evidence_accepted
                else "TEST_FAILED\n缺少成功的实际 pytest 执行证据。"
            )
            return super().generate(
                prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    class _EvidenceAwareReviewerLLM(MockLLM):
        def __init__(self) -> None:
            super().__init__()
            self.evidence_accepted = False

        def generate(
            self,
            prompt: str,
            *,
            system_prompt: str = "",
            temperature: float = 0.2,
            max_tokens: int = 4096,
        ) -> str:
            self.evidence_accepted = (
                "TEST_PASSED" in prompt
                and "exit_code=0" in prompt
                and "2 passed" in prompt
            )
            self.response = (
                "APPROVED\nTester 结论与实际 pytest 证据一致。"
                if self.evidence_accepted
                else "REVISION_REQUIRED\nTester 或实际 pytest 证据不足。"
            )
            return super().generate(
                prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    tester_llm = _EvidenceAwareTesterLLM()
    reviewer_llm = _EvidenceAwareReviewerLLM()
    developer = DeveloperAgent(
        AgentConfig(role="developer", model="deterministic-mock"),
        llm=developer_llm,
    )
    tester = TesterAgent(
        AgentConfig(role="tester", model="deterministic-mock"),
        llm=tester_llm,
    )
    reviewer = ReviewerAgent(
        AgentConfig(role="reviewer", model="deterministic-mock"),
        llm=reviewer_llm,
    )
    router = AgentRouter()
    router.register(developer)
    router.register(tester)
    router.register(reviewer)
    manager = TaskManager([task])
    workflow = TaskWorkflow(
        task_manager=manager,
        developer=developer,
        tester=tester,
        reviewer=reviewer,
        agent_router=router,
        max_review_rounds=1,
    )

    with workspace_scope(tmp_path):
        completed = workflow.execute(task.id)

    assert completed.status == "completed", completed.error
    assert (tmp_path / "calculator.py").is_file()
    assert (tmp_path / "tests" / "test_calculator.py").is_file()

    developer_result = completed.result
    assert developer_result["status"] == "completed"
    developer_data = developer_result["data"]
    assert developer_data["validation"]["test_command_count"] == 1
    assert developer_data["validation"]["files_changed_count"] == 2
    assert len(developer_data["tests"]) == 1
    test_evidence = developer_data["tests"][0]
    assert test_evidence["command"] == "python -m pytest -q tests/test_calculator.py"
    assert test_evidence["result"].startswith("exit_code=0\n")
    assert "2 passed" in test_evidence["result"]

    developer_provenance = provenance_from_value(developer_result)
    tester_feedback = completed.context["tester_feedback"]
    tester_provenance = provenance_from_value(tester_feedback)
    reviewer_result = completed.review_result
    reviewer_provenance = provenance_from_value(reviewer_result)
    assert developer_provenance is not None
    assert tester_provenance is not None
    assert reviewer_provenance is not None
    assert tester_provenance.parent_evidence_id == developer_provenance.evidence_id
    assert reviewer_provenance.parent_evidence_id == tester_provenance.evidence_id
    assert completed.test_result["status"] == "passed"
    assert reviewer_result["status"] == "approved"
    assert len(developer_llm.tool_call_turns) == 3
    assert len(tester_llm.calls) == 1
    assert tester_llm.evidence_accepted is True
    assert "exit_code=0" in tester_llm.calls[0]["prompt"]
    assert "2 passed" in tester_llm.calls[0]["prompt"]
    assert len(reviewer_llm.calls) == 1
    assert reviewer_llm.evidence_accepted is True
    assert "TEST_PASSED" in reviewer_llm.calls[0]["prompt"]
    assert "2 passed" in reviewer_llm.calls[0]["prompt"]


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



def _make_planner_agent(
    *,
    project: str,
    summary: str,
    task_id: str,
    title: str,
    description: str,
):
    """Run the production PlannerAgent with a deterministic, schema-valid model response."""
    from agents.planner import PlannerAgent
    from runtime.agent_config import AgentConfig

    plan = {
        "project": project,
        "summary": summary,
        "tasks": [{
            "id": task_id,
            "title": title,
            "description": description,
            "role": "developer",
            "dependencies": [],
        }],
    }
    llm = MockLLM(response=json.dumps(plan, ensure_ascii=False))
    return PlannerAgent(
        AgentConfig(role="planner", model="deterministic-mock"),
        llm=llm,
    )


def _make_node_project_developer_agent():
    """Use the production DeveloperAgent to scaffold, build and test the Node Web project."""
    from agents.developer import DeveloperAgent
    from runtime.agent_config import AgentConfig
    from runtime.llm.mock import MockLLM

    bootstrap_source = r"""
const fs = require('node:fs');
const path = require('node:path');
const packageJson = {
  name: 'ai-team-orchestrator-web-e2e',
  version: '1.0.0',
  private: true,
  type: 'commonjs',
  scripts: { build: 'node scripts/build.js', test: 'node --test' }
};
const lock = {
  name: packageJson.name,
  version: packageJson.version,
  lockfileVersion: 3,
  requires: true,
  packages: { '': { name: packageJson.name, version: packageJson.version } }
};
function write(relative, content) {
  const target = path.resolve(process.cwd(), relative);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content, 'utf8');
}
write('package.json', JSON.stringify(packageJson, null, 2) + '\n');
write('package-lock.json', JSON.stringify(lock, null, 2) + '\n');
write(
  'src/index.html',
  '<!doctype html><html><body><main>ORCHESTRATOR-WEB-DELIVERABLE</main></body></html>\n'
);
write(
  'scripts/build.js',
  [
    "const fs = require('node:fs');",
    "const path = require('node:path');",
    "const root = process.cwd();",
    "fs.mkdirSync(path.join(root, 'dist'), { recursive: true });",
    "fs.copyFileSync(path.join(root, 'src', 'index.html'), path.join(root, 'dist', 'index.html'));"
  ].join('\n') + '\n'
);
write(
  'tests/app.test.js',
  [
    "const test = require('node:test');",
    "const assert = require('node:assert/strict');",
    "const fs = require('node:fs');",
    "test('built application contains its acceptance marker', () => {",
    "  const html = fs.readFileSync('dist/index.html', 'utf8');",
    "  assert.ok(html.includes('ORCHESTRATOR-WEB-DELIVERABLE'));",
    '});'
  ].join('\n') + '\n'
);
write(
  'tests/test_web_artifact.py',
  [
    'from pathlib import Path',
    '',
    'def test_built_web_entry_contains_acceptance_marker():',
    "    html = Path('dist/index.html').read_text(encoding='utf-8')",
    "    assert 'ORCHESTRATOR-WEB-DELIVERABLE' in html"
  ].join('\n') + '\n'
);
fs.unlinkSync(__filename);
"""
    llm = MockLLM(
        tool_script=[
            {
                "tool_calls": [{
                    "call_id": "developer-write-node-bootstrap",
                    "name": "write_file",
                    "arguments": json.dumps({
                        "path": "bootstrap-project.js",
                        "content": bootstrap_source,
                    }),
                }]
            },
            {
                "tool_calls": [{
                    "call_id": "developer-run-node-bootstrap",
                    "name": "run_command",
                    "arguments": json.dumps({
                        "command": "node bootstrap-project.js",
                        "cwd": ".",
                        "timeout": 90,
                    }),
                }]
            },
            {
                "tool_calls": [{
                    "call_id": "developer-build-node-web",
                    "name": "run_command",
                    "arguments": json.dumps({
                        "command": "npm run build",
                        "cwd": ".",
                        "timeout": 90,
                    }),
                }]
            },
            {
                "tool_calls": [{
                    "call_id": "developer-test-node-web",
                    "name": "run_command",
                    "arguments": json.dumps({
                        "command": "npm test",
                        "cwd": ".",
                        "timeout": 90,
                    }),
                }]
            },
        ]
    )
    return (
        DeveloperAgent(
            AgentConfig(role="developer", model="deterministic-mock"),
            llm=llm,
        ),
        llm,
    )


class _E2ETester:
    role = "tester"

    def run(self, task):
        return {
            "status": "passed",
            "agent": "tester",
            "task_id": task.id,
            "message": "TEST_PASSED: deterministic developer output accepted for integration execution.",
        }


def _make_python_cli_project_gate_agents():
    """Use production Tester/Reviewer agents with pytest-evidence-sensitive decisions."""
    from agents.reviewer import ReviewerAgent
    from agents.tester import TesterAgent
    from runtime.agent_config import AgentConfig
    from runtime.llm.mock import MockLLM

    class _PythonEvidenceAwareTesterLLM(MockLLM):
        def __init__(self) -> None:
            super().__init__()
            self.evidence_accepted = False

        def generate(
            self,
            prompt: str,
            *,
            system_prompt: str = "",
            temperature: float = 0.2,
            max_tokens: int = 4096,
        ) -> str:
            self.evidence_accepted = (
                "python -m pytest -q tests/test_cli.py" in prompt
                and "exit_code=0" in prompt
                and "1 passed" in prompt
            )
            self.response = (
                "TEST_PASSED\n"
                "Developer 的实际 pytest 命令退出码为 0，CLI 测试 1 项通过。"
                if self.evidence_accepted
                else "TEST_FAILED\n"
                "缺少 Python CLI pytest 的成功退出码或通过记录。"
            )
            return super().generate(
                prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    class _PythonEvidenceAwareReviewerLLM(MockLLM):
        def __init__(self) -> None:
            super().__init__()
            self.evidence_accepted = False

        def generate(
            self,
            prompt: str,
            *,
            system_prompt: str = "",
            temperature: float = 0.2,
            max_tokens: int = 4096,
        ) -> str:
            self.evidence_accepted = (
                "TEST_PASSED" in prompt
                and "python -m pytest -q tests/test_cli.py" in prompt
                and "exit_code=0" in prompt
                and "1 passed" in prompt
            )
            self.response = (
                "APPROVED\n"
                "Tester 结论与 Developer 的实际 pytest 执行证据一致。"
                if self.evidence_accepted
                else "REVISION_REQUIRED\n"
                "Tester 结论或实际 pytest 执行证据不足。"
            )
            return super().generate(
                prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    tester_llm = _PythonEvidenceAwareTesterLLM()
    reviewer_llm = _PythonEvidenceAwareReviewerLLM()
    return (
        TesterAgent(
            AgentConfig(role="tester", model="deterministic-mock"),
            llm=tester_llm,
        ),
        tester_llm,
        ReviewerAgent(
            AgentConfig(role="reviewer", model="deterministic-mock"),
            llm=reviewer_llm,
        ),
        reviewer_llm,
    )


def _make_node_project_gate_agents():
    """Use production Tester/Reviewer agents with evidence-sensitive mock decisions."""
    from agents.reviewer import ReviewerAgent
    from agents.tester import TesterAgent
    from runtime.agent_config import AgentConfig
    from runtime.llm.mock import MockLLM

    class _NodeEvidenceAwareTesterLLM(MockLLM):
        def __init__(self) -> None:
            super().__init__()
            self.evidence_accepted = False

        def generate(
            self,
            prompt: str,
            *,
            system_prompt: str = "",
            temperature: float = 0.2,
            max_tokens: int = 4096,
        ) -> str:
            self.evidence_accepted = (
                "npm test" in prompt
                and "exit_code=0" in prompt
                and "pass 1" in prompt
            )
            self.response = (
                "TEST_PASSED\n"
                "Developer 的实际 npm test 命令退出码为 0，Node 测试报告 1 项通过。"
                if self.evidence_accepted
                else "TEST_FAILED\n"
                "缺少 npm test 的成功退出码或实际测试通过记录。"
            )
            return super().generate(
                prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    class _NodeEvidenceAwareReviewerLLM(MockLLM):
        def __init__(self) -> None:
            super().__init__()
            self.evidence_accepted = False

        def generate(
            self,
            prompt: str,
            *,
            system_prompt: str = "",
            temperature: float = 0.2,
            max_tokens: int = 4096,
        ) -> str:
            self.evidence_accepted = (
                "TEST_PASSED" in prompt
                and "npm test" in prompt
                and "exit_code=0" in prompt
                and "pass 1" in prompt
            )
            self.response = (
                "APPROVED\n"
                "Tester 结论与 Developer 的实际 npm test 执行证据一致。"
                if self.evidence_accepted
                else "REVISION_REQUIRED\n"
                "Tester 结论或实际 npm test 执行证据不足。"
            )
            return super().generate(
                prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    tester_llm = _NodeEvidenceAwareTesterLLM()
    reviewer_llm = _NodeEvidenceAwareReviewerLLM()
    return (
        TesterAgent(
            AgentConfig(role="tester", model="deterministic-mock"),
            llm=tester_llm,
        ),
        tester_llm,
        ReviewerAgent(
            AgentConfig(role="reviewer", model="deterministic-mock"),
            llm=reviewer_llm,
        ),
        reviewer_llm,
    )


class _E2EReviewer:
    role = "reviewer"

    def run(self, task):
        return {
            "status": "approved",
            "agent": "reviewer",
            "task_id": task.id,
            "message": "APPROVED: implementation evidence is ready for integration gates.",
        }


def _analyst_spec(project_description: str) -> str:
    return (
        "# 需求规格说明（草案）\n"
        "## 一、项目概述\n"
        f"{project_description}\n"
        "## 二、功能需求清单\n"
        "- REQ-001（必须）项目必须提供可运行且可验证的主要功能。\n"
        "  - AC-001：执行实际验收命令并检查输出与预期一致。\n"
        "## 三、非功能需求\n"
        "- 本地运行，不要求外部云服务。\n"
        "## 四、验收标准\n"
        "- AC-001：关联真实执行的测试 selector。\n"
        "## 五、假设与约束\n"
        "- 使用 CI 提供的受支持工具链。\n"
        "## 六、待确认问题\n"
        "- 无未解决问题。\n"
    )


class _AcceptanceAwareMockLLM(MockLLM):
    """Use observed JUnit selectors for the acceptance mapping; never invent one."""

    def __init__(self) -> None:
        super().__init__(
            response=(
                "# Deterministic project delivery documentation\n\n"
                "REQ-001 is implemented and linked to the executed acceptance test.\n"
                "Install: use the project setup command.\n"
                "Run: use the documented local command.\n"
                "Rollback: restore the previous local package.\n"
            )
        )

    def generate(self, prompt: str, **kwargs) -> str:
        default = super().generate(prompt, **kwargs)
        marker = "实际 JUnit 测试用例：\n"
        if marker not in prompt:
            return default
        raw_cases = prompt.rsplit(marker, 1)[1]
        try:
            cases = json.loads(raw_cases)
        except (TypeError, json.JSONDecodeError):
            cases = []
        selectors = [
            item.get("selector")
            for item in cases
            if isinstance(item, dict) and isinstance(item.get("selector"), str)
        ]
        tests = (
            [{
                "test_id": "AT-001",
                "requirement_id": "REQ-001",
                "selector": selectors[0],
            }]
            if selectors
            else []
        )
        return json.dumps({"schema_version": 1, "tests": tests}, ensure_ascii=False)


def test_acceptance_aware_mock_maps_only_observed_junit_selectors():
    llm = _AcceptanceAwareMockLLM()
    selector = "tests.test_web_artifact::test_built_web_entry_contains_acceptance_marker"
    prompt = (
        "根据需求规格生成映射。\n"
        "实际 JUnit 测试用例：\n"
        + json.dumps([{"selector": selector, "status": "passed"}], ensure_ascii=False)
    )

    result = json.loads(llm.generate(prompt))

    assert result == {
        "schema_version": 1,
        "tests": [{
            "test_id": "AT-001",
            "requirement_id": "REQ-001",
            "selector": selector,
        }],
    }


def test_acceptance_aware_mock_leaves_mapping_empty_without_observed_tests():
    llm = _AcceptanceAwareMockLLM()
    prompt = "实际 JUnit 测试用例：\n[]"

    result = json.loads(llm.generate(prompt))

    assert result == {"schema_version": 1, "tests": []}


class _ResultAwareQAMockLLM(MockLLM):
    """Judge actual QA tool results instead of returning a canned pass."""

    def __init__(
        self,
        *,
        folder: str,
        command: str,
        read_path: str,
        list_path: str,
        expected_list_fragment: str,
        expected_file_fragment: str,
        expected_command_fragment: str,
    ) -> None:
        super().__init__(
            tool_script=[
                {
                    "tool_calls": [{
                        "call_id": f"qa-{folder}-list",
                        "name": "list_files",
                        "arguments": json.dumps({"path": list_path}),
                    }]
                },
                {
                    "tool_calls": [{
                        "call_id": f"qa-{folder}-read",
                        "name": "read_file",
                        "arguments": json.dumps({"path": read_path}),
                    }]
                },
                {
                    "tool_calls": [{
                        "call_id": f"qa-{folder}-execute",
                        "name": "run_command",
                        "arguments": json.dumps({
                            "command": command,
                            "cwd": folder,
                            "timeout": 60,
                        }),
                    }]
                },
            ]
        )
        self.expected_list_fragment = expected_list_fragment
        self.expected_file_fragment = expected_file_fragment
        self.expected_command_fragment = expected_command_fragment
        self.last_tool_assessment = {}

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        if self.remaining_tool_script_steps:
            return super().generate_with_tools(
                messages, tools=tools, tool_choice=tool_choice
            )
        outputs = [
            str(item.get("content", ""))
            for item in messages
            if isinstance(item, dict) and item.get("role") == "tool"
        ]
        # BaseAgent fences every tool result as untrusted data before passing
        # it to the model. Parse the body only when the full expected envelope
        # is present; malformed or unrelated wrappers remain non-passing.
        parsed_outputs = []
        for output in outputs:
            lines = output.splitlines()
            if (
                len(lines) >= 3
                and lines[0].startswith('<untrusted-data source="tool.result.')
                and lines[-1] == "</untrusted-data>"
            ):
                parsed_outputs.append("\n".join(lines[1:-1]))
            else:
                parsed_outputs.append(output)
        self.last_tool_assessment = {
            "tool_output_count": len(outputs),
            "tool_error_count": sum("Tool error:" in item for item in outputs),
            "list_contains_expected": (
                len(parsed_outputs) > 0 and self.expected_list_fragment in parsed_outputs[0]
            ),
            "file_contains_expected": (
                len(parsed_outputs) > 1 and self.expected_file_fragment in parsed_outputs[1]
            ),
            "command_exit_zero": (
                len(parsed_outputs) > 2 and parsed_outputs[2].splitlines()[:1] == ["exit_code=0"]
            ),
            "command_first_line": (
                parsed_outputs[2].splitlines()[:1] if len(parsed_outputs) > 2 else []
            ),
            "command_contains_expected": (
                len(parsed_outputs) > 2 and self.expected_command_fragment in parsed_outputs[2]
            ),
            "tool_error_prefixes": [
                item[:240] for item in outputs if "Tool error:" in item
            ],
        }
        passed = (
            self.last_tool_assessment["tool_output_count"] == 3
            and self.last_tool_assessment["tool_error_count"] == 0
            and self.last_tool_assessment["list_contains_expected"]
            and self.last_tool_assessment["file_contains_expected"]
            and self.last_tool_assessment["command_exit_zero"]
            and self.last_tool_assessment["command_contains_expected"]
        )
        verdict = "QA_PASSED" if passed else "QA_FAILED"
        return LLMResponse(
            content=(
                f"{verdict}\n"
                "- 检查文件列表与交付入口文件。\n"
                "- 根据实际命令退出码确认独立冒烟结果。\n"
            )
        )


def _make_qa_agent(
    *,
    folder: str,
    command: str,
    read_path: str,
    list_path: str,
    expected_list_fragment: str,
    expected_file_fragment: str,
    expected_command_fragment: str,
):
    from agents.qa import QAAgent
    from runtime.agent_config import AgentConfig

    llm = _ResultAwareQAMockLLM(
        folder=folder,
        command=command,
        read_path=read_path,
        list_path=list_path,
        expected_list_fragment=expected_list_fragment,
        expected_file_fragment=expected_file_fragment,
        expected_command_fragment=expected_command_fragment,
    )
    return QAAgent(
        AgentConfig(role="qa", model="deterministic-mock"),
        llm=llm,
        max_tool_iterations=4,
    )

@pytest.mark.skipif(
    os.name != "nt",
    reason="full production ProjectOrchestrator + npm E2E runs on Windows toolchain CI",
)
def test_node_web_requirement_runs_through_project_orchestrator_and_delivery(
    monkeypatch, tmp_path: Path
) -> None:
    from agents.doc_writer import DocWriterAgent
    from agents.analyst import RequirementAnalystAgent
    from core.project_orchestrator import ProjectOrchestrator
    from runtime.agent_config import AgentConfig
    from runtime.agent_router import AgentRouter
    from runtime.llm.mock import MockLLM
    from security.workspace import WorkspaceSandbox

    monkeypatch.setenv("AI_TEAM_PROJECT_ADAPTERS", "1")
    monkeypatch.setenv("AI_TEAM_PROJECT_ADAPTER", "node")
    monkeypatch.setenv("AI_TEAM_STATIC_GATE", "1")
    monkeypatch.setenv("AI_TEAM_INTEGRATION_MAX_ROUNDS", "0")

    sandbox = WorkspaceSandbox(tmp_path)
    planner_agent = _make_planner_agent(
        project="node-web-orchestrator-e2e",
        summary="Deterministic Node.js Web delivery through ProjectOrchestrator",
        task_id="TASK-NODE-WEB-001",
        title="Implement the Node.js Web application",
        description="Create a static web entry, deterministic build and executable test.",
    )
    developer_agent, developer_llm = _make_node_project_developer_agent()
    tester_agent, tester_llm, reviewer_agent, reviewer_llm = _make_node_project_gate_agents()
    qa_agent = _make_qa_agent(
        folder="webapp",
        list_path="webapp/dist",
        read_path="webapp/dist/index.html",
        command="npm test",
        expected_list_fragment="index.html",
        expected_file_fragment="ORCHESTRATOR-WEB-DELIVERABLE",
        expected_command_fragment="pass 1",
    )
    router = AgentRouter()
    for role, agent in (
        (
            "analyst",
            RequirementAnalystAgent(
                AgentConfig(role="analyst", model="deterministic-mock"),
                llm=MockLLM(response=_analyst_spec("A deterministic Node.js Web project.")),
            ),
        ),
        ("planner", planner_agent),
        ("developer", developer_agent),
        ("tester", tester_agent),
        ("reviewer", reviewer_agent),
        (
            "doc_writer",
            DocWriterAgent(
                AgentConfig(role="doc_writer", model="deterministic-mock"),
                llm=_AcceptanceAwareMockLLM(),
                sandbox=sandbox,
            ),
        ),
        (
            "qa",
            qa_agent,
        ),
    ):
        router.register(role, agent)

    project = ProjectOrchestrator(
        agent_router=router,
        project_id="T21-8-NODE-WEB-E2E",
        deliverable_dir="webapp",
        sandbox=sandbox,
    )
    with workspace_scope(tmp_path):
        result = project.run(
            "Create a small Node.js Web project with a reproducible npm lockfile, "
            "a deterministic build, an executable test, and a packaged deliverable. "
            "Do not deploy or publish it."
        )

    assert result.success, result
    assert len(planner_agent.llm.calls) == 1
    assert "Create a small Node.js Web project" in planner_agent.llm.calls[0]["prompt"]
    assert project.last_plan["tasks"][0]["id"] == "TASK-NODE-WEB-001"
    assert result.total_tasks == 1
    assert result.completed_tasks == 1
    task = project.last_task_manager.get_all_tasks()[0]
    from runtime.provenance import provenance_from_value

    tester_feedback = task.context["tester_feedback"]
    developer_provenance = provenance_from_value(task.result)
    tester_provenance = provenance_from_value(tester_feedback)
    reviewer_provenance = provenance_from_value(task.review_result)
    assert developer_provenance is not None
    assert tester_provenance is not None
    assert reviewer_provenance is not None
    assert tester_provenance.parent_evidence_id == developer_provenance.evidence_id
    assert reviewer_provenance.parent_evidence_id == tester_provenance.evidence_id
    assert task.test_result["status"] == "passed"
    assert task.review_result["status"] == "approved"
    assert tester_llm.evidence_accepted is True
    assert "npm test" in tester_llm.calls[0]["prompt"]
    assert "exit_code=0" in tester_llm.calls[0]["prompt"]
    assert "pass 1" in tester_llm.calls[0]["prompt"]
    assert reviewer_llm.evidence_accepted is True
    assert "TEST_PASSED" in reviewer_llm.calls[0]["prompt"]
    assert "exit_code=0" in reviewer_llm.calls[0]["prompt"]
    assert "pass 1" in reviewer_llm.calls[0]["prompt"]
    assert "package.json" in task.context["workspace_merge"]["added"]
    assert "src/index.html" in task.context["workspace_merge"]["added"]
    assert project.last_delivery is not None
    integration = project.last_delivery["integration"]
    assert integration["status"] == "passed"
    assert integration["static"]["status"] == "passed"
    assert integration["static"]["tools"]["ruff"]["status"] == "passed"
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
    developer_records = developer_agent.tool_execution_history.to_dict()
    developer_writes = [record for record in developer_records if record["tool_name"] == "write_file"]
    developer_commands = [record for record in developer_records if record["tool_name"] == "run_command"]
    assert len(developer_writes) == 1
    assert all(record["status"] == "completed" for record in developer_records)
    assert [record["arguments"]["command"] for record in developer_commands] == [
        "node bootstrap-project.js",
        "npm run build",
        "npm test",
    ]
    assert any("exit_code=0" in str(record["output"]) for record in developer_commands)
    assert any("pass 1" in str(record["output"]) for record in developer_commands)
    assert len(developer_llm.tool_call_turns) >= 4
    assert project.last_delivery["qa"]["verdict"] == "QA_PASSED", json.dumps(
        qa_agent.llm.last_tool_assessment, ensure_ascii=False, sort_keys=True
    )
    qa_history = project.last_delivery["qa"]["tool_execution_history"]
    assert len(qa_history) == 3
    assert all(item["status"] == "completed" for item in qa_history)
    assert all("arguments_sha256" in item for item in qa_history)
    assert all("arguments" not in item and "output" not in item for item in qa_history)
    assert project.last_delivery["acceptance"]["executable_verdict"] == "passed"
    accepted_tests = project.last_delivery["acceptance"]["requirements"][0]["tests"]
    assert accepted_tests
    assert all(item["status"] == "passed" for item in accepted_tests)
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
        role_execution={
            "analyst": "requirement_analyst_mock_llm",
            "planner": "production_planner_agent_mock_llm",
            "developer": "production_developer_agent_mock_llm",
            "tester": "production_tester_agent_evidence_aware_mock_llm",
            "reviewer": "production_reviewer_agent_evidence_aware_mock_llm",
            "doc_writer": "mock_llm_observed_junit_mapping",
            "qa": "qa_agent_mock_llm_read_execute_tools",
            "security": "deterministic_gate",
            "sre": "deterministic_gate",
        },
    )
    assert evidence["project_profile"] is not None
    assert evidence["gates"]["integration"]["adapter"]["adapter"] == "node"
    assert evidence["gates"]["analyst"]["status"] == "available"
    assert evidence["gates"]["qa"]["executed_tool_calls"] == 3
    assert evidence["gates"]["acceptance"]["verdict"] == "passed"
    assert evidence["gates"]["acceptance"]["executable_verdict"] == "passed"
    assert evidence["gates"]["security"]["verdict"] == "SEC_PASSED"



def _make_python_cli_project_developer_agent():
    """Use the production DeveloperAgent to scaffold and test the Python CLI project."""
    from agents.developer import DeveloperAgent
    from runtime.agent_config import AgentConfig
    from runtime.llm.mock import MockLLM

    pyproject = (
        "[build-system]\n"
        "requires = ['setuptools>=75']\n"
        "build-backend = 'setuptools.build_meta'\n"
        "[project]\n"
        "name = 'ai-team-orchestrator-cli-e2e'\n"
        "version = '0.1.0'\n"
        "requires-python = '>=3.10'\n"
        "[project.scripts]\n"
        "sample-cli = 'sample_app.cli:main'\n"
        "[tool.setuptools.packages.find]\n"
        "where = ['.']\n"
    )
    cli_source = (
        "import argparse\n\n"
        "def main():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--value', type=int, required=True)\n"
        "    args = parser.parse_args()\n"
        "    print(args.value * 2)\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    test_source = (
        "import subprocess\n"
        "import sys\n\n"
        "def test_cli_success_and_invalid_input():\n"
        "    ok = subprocess.run([sys.executable, '-m', 'sample_app.cli', '--value', '21'], "
        "capture_output=True, text=True, check=False)\n"
        "    assert ok.returncode == 0\n"
        "    assert ok.stdout.strip() == '42'\n"
        "    bad = subprocess.run([sys.executable, '-m', 'sample_app.cli', '--value', 'nope'], "
        "capture_output=True, text=True, check=False)\n"
        "    assert bad.returncode != 0\n"
    )
    readme = (
        "# Sample CLI\n\nInstall with pip install -e . and run "
        "sample-cli --value 21; expected output: 42.\n"
    )
    bootstrap_source = (
        "from pathlib import Path\n"
        "files = {\n"
        f"    'pyproject.toml': {pyproject!r},\n"
        "    'requirements.txt': '',\n"
        "    'sample_app/__init__.py': '',\n"
        f"    'sample_app/cli.py': {cli_source!r},\n"
        f"    'tests/test_cli.py': {test_source!r},\n"
        f"    'README.md': {readme!r},\n"
        "}\n"
        "root = Path.cwd()\n"
        "for relative, content in files.items():\n"
        "    target = root / relative\n"
        "    target.parent.mkdir(parents=True, exist_ok=True)\n"
        "    target.write_text(content, encoding='utf-8')\n"
        "Path(__file__).unlink()\n"
    )
    llm = MockLLM(
        tool_script=[
            {
                "tool_calls": [{
                    "call_id": "developer-write-python-bootstrap",
                    "name": "write_file",
                    "arguments": json.dumps({
                        "path": "bootstrap-project.py",
                        "content": bootstrap_source,
                    }),
                }]
            },
            {
                "tool_calls": [{
                    "call_id": "developer-run-python-bootstrap",
                    "name": "run_command",
                    "arguments": json.dumps({
                        "command": "python bootstrap-project.py",
                        "cwd": ".",
                        "timeout": 90,
                    }),
                }]
            },
            {
                "tool_calls": [{
                    "call_id": "developer-test-python-cli",
                    "name": "run_command",
                    "arguments": json.dumps({
                        "command": "python -m pytest -q tests/test_cli.py",
                        "cwd": ".",
                        "timeout": 90,
                    }),
                }]
            },
        ]
    )
    return (
        DeveloperAgent(
            AgentConfig(role="developer", model="deterministic-mock"),
            llm=llm,
        ),
        llm,
    )


@pytest.mark.skipif(
    os.name != "nt",
    reason="full production ProjectOrchestrator + Python CLI E2E runs on Windows toolchain CI",
)
def test_python_cli_requirement_runs_through_project_orchestrator_and_delivery(
    monkeypatch, tmp_path: Path
) -> None:
    import subprocess

    from agents.doc_writer import DocWriterAgent
    from agents.analyst import RequirementAnalystAgent
    from core.project_orchestrator import ProjectOrchestrator
    from runtime.agent_config import AgentConfig
    from runtime.agent_router import AgentRouter
    from runtime.llm.mock import MockLLM
    from security.workspace import WorkspaceSandbox

    monkeypatch.setenv("AI_TEAM_PROJECT_ADAPTERS", "1")
    monkeypatch.setenv("AI_TEAM_PROJECT_ADAPTER", "python")
    monkeypatch.setenv("AI_TEAM_STATIC_GATE", "1")
    monkeypatch.setenv("AI_TEAM_INTEGRATION_MAX_ROUNDS", "0")

    sandbox = WorkspaceSandbox(tmp_path)
    planner_agent = _make_planner_agent(
        project="python-cli-orchestrator-e2e",
        summary="Deterministic Python CLI delivery through ProjectOrchestrator",
        task_id="TASK-PYTHON-CLI-001",
        title="Implement the Python CLI application",
        description="Create an installable CLI package with executable tests.",
    )
    developer_agent, developer_llm = _make_python_cli_project_developer_agent()
    tester_agent, tester_llm, reviewer_agent, reviewer_llm = _make_python_cli_project_gate_agents()
    qa_agent = _make_qa_agent(
        folder="cli",
        list_path="cli/sample_app",
        read_path="cli/sample_app/cli.py",
        command="python -m sample_app.cli --value 21",
        expected_list_fragment="cli.py",
        expected_file_fragment="def main",
        expected_command_fragment="42",
    )
    router = AgentRouter()
    for role, agent in (
        (
            "analyst",
            RequirementAnalystAgent(
                AgentConfig(role="analyst", model="deterministic-mock"),
                llm=MockLLM(response=_analyst_spec("An installable Python CLI project.")),
            ),
        ),
        ("planner", planner_agent),
        ("developer", developer_agent),
        ("tester", tester_agent),
        ("reviewer", reviewer_agent),
        (
            "doc_writer",
            DocWriterAgent(
                AgentConfig(role="doc_writer", model="deterministic-mock"),
                llm=_AcceptanceAwareMockLLM(),
                sandbox=sandbox,
            ),
        ),
        (
            "qa",
            qa_agent,
        ),
    ):
        router.register(role, agent)

    project = ProjectOrchestrator(
        agent_router=router,
        project_id="T21-8-PYTHON-CLI-E2E",
        deliverable_dir="cli",
        sandbox=sandbox,
    )
    with workspace_scope(tmp_path):
        result = project.run(
            "Create an installable Python CLI package with reproducible setup, "
            "a documented command, tests for valid and invalid input, and a package. "
            "Do not publish or deploy it."
        )

    assert result.success, result
    assert len(planner_agent.llm.calls) == 1
    assert "Create an installable Python CLI package" in planner_agent.llm.calls[0]["prompt"]
    assert project.last_plan["tasks"][0]["id"] == "TASK-PYTHON-CLI-001"
    assert result.total_tasks == 1
    assert result.completed_tasks == 1
    task = project.last_task_manager.get_all_tasks()[0]
    from runtime.provenance import provenance_from_value

    tester_feedback = task.context["tester_feedback"]
    developer_provenance = provenance_from_value(task.result)
    tester_provenance = provenance_from_value(tester_feedback)
    reviewer_provenance = provenance_from_value(task.review_result)
    assert developer_provenance is not None
    assert tester_provenance is not None
    assert reviewer_provenance is not None
    assert tester_provenance.parent_evidence_id == developer_provenance.evidence_id
    assert reviewer_provenance.parent_evidence_id == tester_provenance.evidence_id
    assert task.test_result["status"] == "passed"
    assert task.review_result["status"] == "approved"
    assert tester_llm.evidence_accepted is True
    assert "python -m pytest -q tests/test_cli.py" in tester_llm.calls[0]["prompt"]
    assert "exit_code=0" in tester_llm.calls[0]["prompt"]
    assert "1 passed" in tester_llm.calls[0]["prompt"]
    assert reviewer_llm.evidence_accepted is True
    assert "TEST_PASSED" in reviewer_llm.calls[0]["prompt"]
    assert "exit_code=0" in reviewer_llm.calls[0]["prompt"]
    assert "1 passed" in reviewer_llm.calls[0]["prompt"]
    assert "pyproject.toml" in task.context["workspace_merge"]["added"]
    assert "sample_app/cli.py" in task.context["workspace_merge"]["added"]
    assert "bootstrap-project.py" not in task.context["workspace_merge"]["added"]
    developer_records = developer_agent.tool_execution_history.to_dict()
    developer_writes = [record for record in developer_records if record["tool_name"] == "write_file"]
    developer_commands = [record for record in developer_records if record["tool_name"] == "run_command"]
    assert len(developer_writes) == 1
    assert all(record["status"] == "completed" for record in developer_records)
    developer_command_sequence = [
        record["arguments"]["command"] for record in developer_commands
    ]
    assert len(developer_command_sequence) >= 2
    assert developer_command_sequence[-2:] == [
        "python bootstrap-project.py",
        "python -m pytest -q tests/test_cli.py",
    ]
    assert all("exit_code=0" in str(record["output"]) for record in developer_commands)
    assert any(
        record["arguments"]["command"] == "python -m pytest -q tests/test_cli.py"
        and "1 passed" in str(record["output"])
        for record in developer_commands
    )
    assert len(developer_llm.tool_call_turns) >= 3
    assert project.last_delivery is not None
    integration = project.last_delivery["integration"]
    assert integration["status"] == "passed"
    assert integration["static"]["status"] == "passed"
    assert integration["static"]["tools"]["ruff"]["status"] == "passed"
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
    assert project.last_delivery["qa"]["verdict"] == "QA_PASSED", json.dumps(
        qa_agent.llm.last_tool_assessment, ensure_ascii=False, sort_keys=True
    )
    assert project.last_delivery["acceptance"]["verdict"] == "passed"
    qa_history = project.last_delivery["qa"]["tool_execution_history"]
    assert len(qa_history) == 3
    assert all(item["status"] == "completed" for item in qa_history)
    assert all("arguments_sha256" in item for item in qa_history)
    assert all("arguments" not in item and "output" not in item for item in qa_history)
    assert project.last_delivery["acceptance"]["executable_verdict"] == "passed"
    accepted_tests = project.last_delivery["acceptance"]["requirements"][0]["tests"]
    assert accepted_tests
    assert all(item["status"] == "passed" for item in accepted_tests)
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
        role_execution={
            "analyst": "requirement_analyst_mock_llm",
            "planner": "production_planner_agent_mock_llm",
            "developer": "production_developer_agent_mock_llm",
            "tester": "production_tester_agent_evidence_aware_mock_llm",
            "reviewer": "production_reviewer_agent_evidence_aware_mock_llm",
            "doc_writer": "mock_llm_observed_junit_mapping",
            "qa": "qa_agent_mock_llm_read_execute_tools",
            "security": "deterministic_gate",
            "sre": "deterministic_gate",
        },
    )
    assert evidence["project_profile"]["project_type"] == "cli"
    assert evidence["gates"]["analyst"]["status"] == "available"
    assert evidence["gates"]["qa"]["executed_tool_calls"] == 3
    assert evidence["gates"]["acceptance"]["verdict"] == "passed"
    assert evidence["gates"]["acceptance"]["executable_verdict"] == "passed"
    assert evidence["gates"]["security"]["verdict"] == "SEC_PASSED"
