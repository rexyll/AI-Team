"""QA adversarial agent contracts: verdict parsing, bounded tool loop,
capability enforcement (no WRITE tools for the qa role)."""

from __future__ import annotations

from pathlib import Path

from agents.qa import QAAgent, parse_qa_verdict
from runtime.agent_config import AgentConfig
from runtime.llm.base import BaseLLM, LLMResponse, LLMToolCall
from runtime.task import Task
from security.workspace import get_default_workspace_root, set_default_workspace_root


class _ScriptedLLM(BaseLLM):
    """Returns scripted responses in order for generate_with_tools."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        raise AssertionError("not used")

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


def test_parse_qa_verdict_accepts_only_literal_first_line():
    assert parse_qa_verdict("QA_PASSED\nevidence...") == "QA_PASSED"
    assert parse_qa_verdict("  QA_FAILED\nx") == "QA_FAILED"
    assert parse_qa_verdict("all good") == "unknown"
    assert parse_qa_verdict("") == "unknown"
    assert parse_qa_verdict(None) == "unknown"


def test_qa_agent_without_tool_calls_returns_verdict():
    llm = _ScriptedLLM([LLMResponse(content="QA_PASSED\n用例 1：正常执行。")])
    agent = QAAgent(AgentConfig(role="qa", model=""), llm=llm)
    task = Task(id="QA-001", title="t", description="d", role="qa", status="ready")

    result = agent.run(task)

    assert result.status == "completed"
    assert result.data["qa"]["verdict"] == "QA_PASSED"
    assert result.data["qa"]["executed_tool_calls"] == 0
    assert llm.calls == 1


def test_qa_agent_executes_read_tools_and_parses_final_verdict(tmp_path: Path):
    previous_root = get_default_workspace_root()
    set_default_workspace_root(tmp_path)
    try:
        (tmp_path / "e2e_flat").mkdir()
        (tmp_path / "e2e_flat" / "todo.py").write_text("x = 1", encoding="utf-8")
        llm = _ScriptedLLM([
            LLMResponse(
                content=None,
                tool_calls=(LLMToolCall(call_id="c1", name="list_files", arguments='{"path": "e2e_flat"}'),),
            ),
            LLMResponse(content="QA_PASSED\n用例 1：目录浏览正常。"),
        ])
        agent = QAAgent(AgentConfig(role="qa", model=""), llm=llm)
        task = Task(id="QA-001", title="t", description="d", role="qa", status="ready")

        result = agent.run(task)

        assert result.data["qa"]["verdict"] == "QA_PASSED"
        assert result.data["qa"]["executed_tool_calls"] == 1
        assert llm.calls == 2
    finally:
        set_default_workspace_root(previous_root)


def test_qa_agent_denies_write_tools_and_survives(tmp_path: Path):
    previous_root = get_default_workspace_root()
    set_default_workspace_root(tmp_path)
    try:
        llm = _ScriptedLLM([
            LLMResponse(
                content=None,
                tool_calls=(LLMToolCall(call_id="c1", name="write_file", arguments='{"path": "hack.py", "content": "x = 1"}'),),
            ),
            LLMResponse(content="QA_FAILED\n写入尝试被拒绝，无法进一步验证。"),
        ])
        agent = QAAgent(AgentConfig(role="qa", model=""), llm=llm)
        task = Task(id="QA-001", title="t", description="d", role="qa", status="ready")

        result = agent.run(task)

        # The denied call never executed; the loop survived and produced a verdict.
        assert result.status == "completed"
        assert result.data["qa"]["executed_tool_calls"] == 0
        assert result.data["qa"]["verdict"] == "QA_FAILED"
        assert not (tmp_path / "hack.py").exists()
    finally:
        set_default_workspace_root(previous_root)


def test_qa_agent_rejects_invalid_construction():
    import pytest

    with pytest.raises(ValueError):
        QAAgent(AgentConfig(role="qa", model=""), max_tool_iterations=0)
    with pytest.raises(TypeError):
        QAAgent(AgentConfig(role="qa", model=""), max_tool_iterations="3")
