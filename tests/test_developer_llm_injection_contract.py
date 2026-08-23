"""Contract tests for the DeveloperAgent LLM injection boundary.

Regression guard for the defect where ``DeveloperAgent.run()`` bypassed the
constructor-injected ``BaseLLM`` and called the module-level provider client
directly. These tests prove that the tool-calling loop routes through the
injected LLM and that deterministic mocks can drive it end to end.
"""

from __future__ import annotations

import json

import pytest

import security.workspace as workspace_module
from agents.developer import DeveloperAgent
from runtime.llm.mock import MockLLM
from runtime.llm.provider import ProviderLLM
from runtime.task import Task
from security.workspace import WorkspaceSandbox


def _make_task() -> Task:
    return Task(
        id="TASK-INJECT-001",
        title="write a note file",
        description="Create notes.txt inside the workspace.",
        role="developer",
    )


def test_default_developer_still_uses_provider_llm() -> None:
    agent = DeveloperAgent()

    assert isinstance(agent.llm, ProviderLLM)


def test_run_routes_through_injected_mock_and_executes_real_tool(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        workspace_module,
        "DEFAULT_SANDBOX",
        WorkspaceSandbox(tmp_path),
    )

    llm = MockLLM(
        "Implemented notes.txt with a greeting.",
        tool_script=[
            {
                "tool_calls": [
                    {
                        "call_id": "call-001",
                        "name": "write_file",
                        "arguments": json.dumps(
                            {"path": "notes.txt", "content": "hello from smoke"}
                        ),
                    }
                ]
            }
        ],
    )
    agent = DeveloperAgent(llm=llm)
    result = agent.run(_make_task())

    # The injected mock actually drove the loop (regression proof).
    assert llm.tool_call_turns, "DeveloperAgent.run() must use the injected LLM"

    assert result.status == "completed"
    assert result.agent == "developer"
    assert result.task_id == "TASK-INJECT-001"
    assert result.data["files_changed"] == ["notes.txt"]
    assert result.data["validation"]["tool_call_count"] == 1

    # The scripted tool call executed the real registry tool inside the sandbox.
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello from smoke"

    record = agent.tool_execution_history.get("call-001")
    assert record.tool_name == "write_file"
    assert record.status == "completed"
    assert record.arguments["path"] == "notes.txt"


def test_text_only_mock_completes_without_tool_calls(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        workspace_module,
        "DEFAULT_SANDBOX",
        WorkspaceSandbox(tmp_path),
    )

    agent = DeveloperAgent(llm=MockLLM("plain final answer"))
    result = agent.run(_make_task())

    assert result.status == "completed"
    assert result.message == "plain final answer"
    assert result.data["validation"]["tool_call_count"] == 0
    assert len(agent.tool_execution_history) == 0


def test_script_exhaustion_falls_back_to_final_answer(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        workspace_module,
        "DEFAULT_SANDBOX",
        WorkspaceSandbox(tmp_path),
    )

    agent = DeveloperAgent(llm=MockLLM("terminal answer"))
    result = agent.run(_make_task())

    assert result.status == "completed"
    assert result.message == "terminal answer"


@pytest.mark.parametrize(
    "script",
    [
        [123],
        [{"tool_calls": "not-a-list"}],
        [{"tool_calls": [{"call_id": 1, "name": "x", "arguments": "{}"}]}],
        [{"unexpected": True}],
    ],
)
def test_invalid_tool_scripts_are_rejected(script) -> None:
    with pytest.raises(TypeError):
        MockLLM(tool_script=script)


def test_string_script_steps_are_valid_final_answers() -> None:
    llm = MockLLM(tool_script=["plain text turn"])

    response = llm.generate_with_tools([])

    assert response.content == "plain text turn"
    assert response.tool_calls == ()
