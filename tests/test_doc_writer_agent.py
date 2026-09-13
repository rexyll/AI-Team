from __future__ import annotations

from pathlib import Path

from agents.doc_writer import DocWriterAgent, DOC_SPECS
from runtime.agent_config import AgentConfig
from runtime.llm.base import BaseLLM
from runtime.task import Task
from security.workspace import WorkspaceSandbox


class _FixedLLM(BaseLLM):
    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        return f"# 文档正文\n\n基于上下文生成的内容（{len(prompt)} 字符提示）。\n"

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        raise AssertionError("doc writer must not use tool calling")


def _writer(sandbox: WorkspaceSandbox) -> DocWriterAgent:
    return DocWriterAgent(AgentConfig(role="doc_writer", model=""), llm=_FixedLLM(), sandbox=sandbox)


def _delivery_task() -> Task:
    task = Task(
        id="DELIVERY-001", title="生成交付文档", description="撰写文档",
        role="doc_writer", status="ready",
    )
    task.context["deliverable_dir"] = "e2e_flat"
    task.context["requirement_analysis"] = "# 需求规格说明（草案）\n## 二、功能需求清单\nREQ-001 词频统计"
    task.context["plan_summary"] = {"project": "wordcount", "summary": "词频统计工具"}
    task.context["task_digest"] = [
        {"id": "TASK-002", "role": "developer", "title": "实现 wordcount.py",
         "status": "completed", "report": "实现完成，测试通过", "test_evidence_count": 2},
    ]
    return task


def test_doc_writer_produces_full_document_set(tmp_path: Path):
    sandbox = WorkspaceSandbox(tmp_path)

    result = _writer(sandbox).run(_delivery_task())

    assert result.status == "completed"
    assert len(result.data["docs"]) == len(DOC_SPECS)
    for spec in DOC_SPECS:
        doc_path = tmp_path / "e2e_flat" / "docs" / spec[0]
        assert doc_path.is_file(), spec[0]
        assert doc_path.read_text(encoding="utf-8").strip()


def test_doc_writer_writes_inside_deliverable_dir_only(tmp_path: Path):
    sandbox = WorkspaceSandbox(tmp_path)

    result = _writer(sandbox).run(_delivery_task())

    paths = {item["path"] for item in result.data["docs"]}
    assert all(path.startswith(str((tmp_path / "e2e_flat" / "docs"))) for path in paths)


def test_doc_writer_falls_back_to_workspace_root(tmp_path: Path):
    sandbox = WorkspaceSandbox(tmp_path)
    task = _delivery_task()
    task.context["deliverable_dir"] = ""

    result = _writer(sandbox).run(task)

    assert (tmp_path / "docs" / DOC_SPECS[0][0]).is_file()
    assert result.data["docs_root"] == "docs"
