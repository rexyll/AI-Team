"""Cross-project knowledge base contracts (TaskPlan T11).

Deterministic extraction from delivery evidence, durable deduplicated storage,
filtered loading (kind/tag/role/keyword), prompt rendering, backfill extraction
from a finished deliverable, and orchestrator wiring (load before analysis,
extract after delivery).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.analyst import RequirementAnalystAgent, run_quality_checked_analysis
from core.project_orchestrator import ProjectOrchestrator
from runtime.agent_config import AgentConfig
from runtime.agent_result import AgentResult
from runtime.agent_router import AgentRouter
from runtime.knowledge_base import (
    KNOWLEDGE_KINDS,
    KnowledgeBase,
    KnowledgeEntry,
    build_knowledge_prompt,
    extract_deliverable_knowledge,
    extract_delivery_knowledge,
    make_entry_id,
    parse_acceptance_report,
    render_knowledge_list,
    render_knowledge_prompt,
)
from runtime.llm.base import BaseLLM
from runtime.task import Task
from security.workspace import WorkspaceSandbox

ANALYSIS_MARKDOWN = """# 需求规格说明（草案）

## 一、项目概述
待办事项 CLI 工具。

## 二、功能需求清单
### REQ-001 待办管理（必须）
支持添加、列出、完成任务。
验收标准：CLI 命令实际可运行。

## 三、非功能需求
-【假设】单机运行。

## 四、验收标准
见 REQ-001。

## 五、假设与约束
-【假设】JSON 存储。

## 六、待确认问题
无。
"""


def _entry(
    kind: str,
    title: str,
    *,
    project: str = "history",
    tags: tuple[str, ...] = (),
    roles: tuple[str, ...] = (),
    created_at: str = "2026-11-01T00:00:00Z",
    body: str | None = None,
) -> KnowledgeEntry:
    return KnowledgeEntry(
        entry_id=make_entry_id(kind, project, title),
        kind=kind,
        title=title,
        body=body or f"关于 {title} 的经验。",
        source_project=project,
        tags=tags,
        roles=roles,
        created_at=created_at,
    )


def _delivery(**overrides) -> dict:
    delivery = {
        "docs_root": "deliver/docs",
        "deliverable_root": "deliver",
        "docs": [],
        "manifest": None,
        "acceptance": None,
        "integration": None,
        "qa": None,
        "dependency_scan": None,
        "usage": None,
        "release": None,
    }
    delivery.update(overrides)
    return delivery


def test_extract_delivery_knowledge_captures_gates_and_dependency_findings():
    delivery = _delivery(
        acceptance={
            "verdict": "failed",
            "gaps": ["REQ-001 未在 test_report 中追溯"],
            "warnings": ["REQ-002（可选）未在 design_doc 中追溯"],
        },
        integration={
            "status": "failed",
            "rounds": 2,
            "suite": {"failed_tests": ["test_todo.py::test_ok"]},
            "static": {"status": "failed", "tools": {"ruff": {"status": "failed", "enforced": True}}},
        },
        qa={"verdict": "QA_FAILED", "message_head": "boundary input crashes"},
        dependency_scan={
            "status": "completed",
            "requirements_file": "requirements.txt",
            "declared": ["requests"],
            "unpinned": ["requests"],
            "undeclared_imports": ["yaml"],
        },
    )

    entries = extract_delivery_knowledge(delivery, project="todo", created_at="2026-11-02T00:00:00Z")

    assert entries
    assert all(entry.kind in KNOWLEDGE_KINDS for entry in entries)
    ids = [entry.entry_id for entry in entries]
    assert len(ids) == len(set(ids))
    titles = [entry.title for entry in entries]
    assert any("REQ-001 未在 test_report 中追溯" in title for title in titles)
    assert any("REQ-002（可选）" in title for title in titles)
    assert any("集成回归失败" in title for title in titles)
    assert any("静态质量门禁未通过" in title for title in titles)
    assert any("QA 对抗测试未通过" in title for title in titles)
    assert any("依赖声明不完整" in title for title in titles)
    gap_entry = next(entry for entry in entries if "REQ-001" in entry.title)
    assert set(gap_entry.tags) >= {"acceptance", "gap", "REQ-001"}
    assert set(gap_entry.roles) >= {"analyst", "developer", "tester", "doc_writer"}
    # No baseline pattern is invented for a red delivery.
    assert not any(entry.kind == "pattern" for entry in entries)


def test_extract_green_delivery_yields_baseline_pattern_and_conventions():
    delivery = _delivery(
        acceptance={"verdict": "passed", "gaps": [], "warnings": []},
        integration={"status": "passed", "rounds": 0, "suite": {"summary": {"passed": 3}}, "static": {"status": "passed"}},
        qa={"verdict": "QA_PASSED"},
        dependency_scan={
            "status": "completed",
            "requirements_file": "requirements.txt",
            "declared": ["requests==2.31.0"],
            "unpinned": [],
            "undeclared_imports": [],
        },
        release={"status": "released", "version": "0.2.0", "tag": "v0.2.0"},
        docs=[{"document": str(index)} for index in range(5)],
    )

    entries = extract_delivery_knowledge(
        delivery, project="ledger", created_at="2026-11-02T00:00:00Z"
    )

    baseline = next(entry for entry in entries if entry.kind == "pattern")
    assert "绿色交付基线" in baseline.title
    assert set(baseline.roles) >= {"analyst", "developer", "doc_writer"}
    assert any("依赖声明与导入一致" in entry.title for entry in entries)
    assert any("发布锚点" in entry.title and "v0.2.0" in entry.body for entry in entries)
    # Deterministic identity across repeated extraction.
    again = extract_delivery_knowledge(
        delivery, project="ledger", created_at="2026-11-02T00:00:00Z"
    )
    assert [entry.entry_id for entry in entries] == [entry.entry_id for entry in again]


def test_knowledge_base_add_deduplicates_and_round_trips(tmp_path: Path):
    store = KnowledgeBase(tmp_path / "knowledge")
    entries = [
        _entry("pitfall", "集成回归失败"),
        _entry("convention", "依赖版本钉死"),
    ]

    first = store.add(entries)
    second = store.add(entries)

    assert first == {"added": 2, "duplicates": 0, "total": 2}
    assert second == {"added": 0, "duplicates": 2, "total": 2}
    assert (tmp_path / "knowledge" / "knowledge_base.json").is_file()
    loaded = store.load()
    assert [entry.entry_id for entry in loaded] == [entry.entry_id for entry in entries]
    assert loaded[0].to_dict() == entries[0].to_dict()

    # A direct .json path is accepted as the store location.
    direct = KnowledgeBase(tmp_path / "custom.json")
    direct.save(entries)
    assert direct.path.name == "custom.json"
    assert len(direct.load()) == 2


def test_knowledge_base_fails_closed_on_corruption(tmp_path: Path):
    store = KnowledgeBase(tmp_path / "knowledge")
    assert store.load() == []

    store.path.parent.mkdir(parents=True)
    store.path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid knowledge base"):
        store.load()

    store.path.write_text(json.dumps({"entries": "oops"}), encoding="utf-8")
    with pytest.raises(ValueError, match="entries"):
        store.load()

    store.path.write_text(json.dumps({"entries": [{"kind": "unknown"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid entry"):
        store.load()


def test_search_filters_by_kind_tag_role_keyword_and_limit(tmp_path: Path):
    store = KnowledgeBase(tmp_path / "knowledge")
    gap = _entry("pitfall", "验收缺口：REQ-001 未追溯", tags=("acceptance", "gap"), roles=("analyst", "tester"))
    rework = _entry("pitfall", "集成回归需 1 轮返工", tags=("integration",), roles=("developer",), created_at="2026-11-02T00:00:00Z")
    convention = _entry("convention", "发布锚点：semver + tag", tags=("release",), roles=("doc_writer",))
    store.save([gap, convention, rework])

    assert {entry.entry_id for entry in store.search(kinds=("pitfall",))} == {gap.entry_id, rework.entry_id}
    assert [entry.entry_id for entry in store.search(tags=("release",))] == [convention.entry_id]
    assert [entry.entry_id for entry in store.search(roles=("doc_writer",))] == [convention.entry_id]
    assert [entry.entry_id for entry in store.search(query="返工")] == [rework.entry_id]
    # Newest pitfall first under the kind-priority ordering.
    assert [entry.entry_id for entry in store.search(limit=2)] == [rework.entry_id, gap.entry_id]
    assert store.search(limit=0) == []
    assert store.search(limit=None) and len(store.search(limit=None)) == 3

    with pytest.raises(ValueError, match="unknown knowledge kinds"):
        store.search(kinds=("lesson",))
    with pytest.raises(ValueError, match="limit"):
        store.search(limit=-1)
    with pytest.raises(TypeError):
        store.add(gap)


def test_render_helpers_and_disabled_store(tmp_path: Path):
    assert render_knowledge_prompt([]) == ""
    assert render_knowledge_list([]).splitlines()[-1].startswith("| （无知识资产）")
    assert build_knowledge_prompt(None) == ""

    store = KnowledgeBase(tmp_path / "knowledge")
    store.add([_entry("pitfall", "未声明的第三方导入", tags=("dependency",), roles=("developer",))])
    prompt = build_knowledge_prompt(store.path, roles=("developer",))
    assert "跨项目知识资产" in prompt
    assert "[坑] 未声明的第三方导入" in prompt
    assert build_knowledge_prompt(store.path, roles=("doc_writer",)) == ""
    listing = render_knowledge_list(store.load())
    assert "| 编号 | 类型 |" in listing
    assert "第三方导入" in listing


def test_extract_deliverable_knowledge_reads_release_log_and_acceptance_report(tmp_path: Path):
    deliverable = tmp_path / "ledger"
    (deliverable / "docs").mkdir(parents=True)
    (deliverable / "release_log.json").write_text(
        json.dumps({
            "releases": [{
                "version": "0.1.0",
                "tag": "v0.1.0",
                "project": "ledger",
                "acceptance_verdict": "failed",
                "integration_status": "failed",
                "integration_rounds": 1,
            }]
        }),
        encoding="utf-8",
    )
    (deliverable / "docs" / "acceptance_report.md").write_text(
        "# 需求验收报告（Acceptance Report）\n\n"
        "验收结论：**FAILED**\n\n"
        "## 验收缺口\n\n"
        "- REQ-001 未在 test_report 中追溯\n\n"
        "## 警告\n\n"
        "- REQ-002（可选）未在 user_manual 中追溯\n\n"
        "生成时间：2026-11-01T00:00:00Z\n",
        encoding="utf-8",
    )

    entries = extract_deliverable_knowledge(deliverable, created_at="2026-11-02T00:00:00Z")

    assert entries
    assert {entry.source_project for entry in entries} == {"ledger"}
    assert any("REQ-001" in entry.title for entry in entries)
    assert any("REQ-002" in entry.title for entry in entries)
    assert any("集成回归失败" in entry.title for entry in entries)
    assert any("发布锚点" in entry.title for entry in entries)

    # A directory with no delivery artifacts yields nothing to learn.
    empty = tmp_path / "empty"
    empty.mkdir()
    assert extract_deliverable_knowledge(empty) == []

    # A corrupt release log fails closed.
    (deliverable / "release_log.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid release log"):
        extract_deliverable_knowledge(deliverable)


def test_parse_acceptance_report_is_deterministic():
    text = (
        "验收结论：**PASSED**\n\n"
        "## 验收缺口\n\n"
        "## 警告\n\n"
        "- REQ-003（可选）未在 design_doc 中追溯\n"
    )
    assert parse_acceptance_report(text) == {
        "verdict": "passed",
        "gaps": [],
        "warnings": ["REQ-003（可选）未在 design_doc 中追溯"],
    }


class _FixedTextLLM(BaseLLM):
    def __init__(self, text: str):
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        self.prompts.append(prompt)
        return self.text

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        raise AssertionError("not used")


def test_analyst_prompt_includes_fenced_knowledge():
    llm = _FixedTextLLM(ANALYSIS_MARKDOWN)
    analyst = RequirementAnalystAgent(AgentConfig(role="analyst", model=""), llm=llm)

    result = run_quality_checked_analysis(
        analyst,
        requirement="开发一个待办事项 CLI 工具",
        knowledge="### 跨项目知识资产（历史交付沉淀）\n- [坑] 集成回归失败",
    )

    assert result.data["attempts"] == 1
    prompt = llm.prompts[0]
    assert "历史交付经验（跨项目知识库" in prompt
    assert "<untrusted-data" in prompt
    assert "不得把历史项目的路径、命名或技术选型当作本项目的约束" in prompt


class _StubPlanner:
    role = "planner"

    def run(self, task: Task) -> dict:
        return {
            "plan": {
                "project": "todo",
                "summary": "待办事项 CLI 工具",
                "tasks": [{
                    "id": "TASK-001",
                    "title": "实现待办说明文件",
                    "description": "在 deliver/ 下写 note.txt",
                    "role": "developer",
                    "dependencies": [],
                }],
            }
        }


class _DocWriterStub:
    role = "doc_writer"

    def __init__(self, deliverable: Path) -> None:
        self._deliverable = deliverable
        self.tasks: list[Task] = []

    def run(self, task: Task) -> AgentResult:
        self.tasks.append(task)
        docs_root = self._deliverable / "docs"
        docs_root.mkdir(parents=True, exist_ok=True)
        written = []
        for filename, title in (
            ("requirements.md", "需求规格说明书"),
            ("design.md", "设计文档"),
            ("test_report.md", "测试结果报告"),
            ("deployment.md", "部署指引"),
            ("user_manual.md", "用户手册"),
        ):
            (docs_root / filename).write_text(
                f"# {title}\n\nREQ-001 已实现；集成回归证据见下。\n", encoding="utf-8"
            )
            written.append({"document": title, "path": str(docs_root / filename), "filename": filename})
        return AgentResult(
            status="completed",
            agent=self.role,
            task_id=task.id,
            message="docs written",
            data={"docs": written, "docs_root": "deliver/docs"},
        )


def test_orchestrator_loads_knowledge_before_analysis_and_extracts_after_delivery(tmp_path: Path):
    knowledge_dir = tmp_path / "knowledge"
    KnowledgeBase(knowledge_dir).save([
        _entry(
            "pitfall",
            "验收缺口：必须级需求未追溯",
            project="earlier",
            tags=("acceptance",),
            roles=("analyst", "doc_writer"),
        )
    ])
    deliverable = tmp_path / "deliver"
    analyst_llm = _FixedTextLLM(ANALYSIS_MARKDOWN)
    doc_writer = _DocWriterStub(deliverable)
    router = AgentRouter()
    router.register(
        "analyst",
        RequirementAnalystAgent(AgentConfig(role="analyst", model=""), llm=analyst_llm),
    )
    router.register("planner", _StubPlanner())
    router.register("doc_writer", doc_writer)
    orchestrator = ProjectOrchestrator(
        agent_router=router,
        deliverable_dir="deliver",
        sandbox=WorkspaceSandbox(tmp_path),
        knowledge_base=str(knowledge_dir),
    )

    plan = orchestrator.create_plan("开发一个待办事项 CLI 工具")
    task_manager = orchestrator.build_task_manager(plan)
    task_manager.mark_ready("TASK-001")
    task_manager.mark_running("TASK-001")
    task_manager.record_result("TASK-001", {"message": "实现完成", "data": {"tests": [{"command": "python -m pytest"}]}})
    task_manager.mark_completed("TASK-001")

    delivery = orchestrator._run_delivery_phase(task_manager, project="todo")

    # Loaded before analysis and before documentation.
    assert delivery is not None
    assert "跨项目知识资产" in analyst_llm.prompts[0]
    assert "验收缺口：必须级需求未追溯" in analyst_llm.prompts[0]
    assert doc_writer.tasks[0].context["knowledge_assets"].startswith("### 跨项目知识资产")

    # Extracted after delivery: a green delivery yields the baseline pattern.
    assert delivery["knowledge"]["status"] == "completed"
    assert delivery["knowledge"]["added"] >= 1
    stored = KnowledgeBase(knowledge_dir).load()
    assert any("绿色交付基线" in entry.title for entry in stored)
    assert len({entry.entry_id for entry in stored}) == len(stored)

    # Re-delivering the same evidence dedupes instead of growing the store.
    second_manager = orchestrator.build_task_manager(orchestrator.create_plan("开发一个待办事项 CLI 工具"))
    second_manager.mark_ready("TASK-001")
    second_manager.mark_running("TASK-001")
    second_manager.record_result("TASK-001", {"message": "实现完成", "data": {"tests": [{"command": "python -m pytest"}]}})
    second_manager.mark_completed("TASK-001")
    second = orchestrator._run_delivery_phase(second_manager, project="todo")
    assert second is not None
    assert second["knowledge"]["added"] == 0
    assert second["knowledge"]["duplicates"] >= 1
