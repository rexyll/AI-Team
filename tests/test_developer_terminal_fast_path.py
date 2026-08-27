from runtime.llm.mock import MockLLM
from runtime.task import Task
from agents.developer import DeveloperAgent


def test_developer_terminal_verification_fast_path_avoids_followup_llm_turn() -> None:
    llm = MockLLM(
        tool_script=[
            {
                "tool_calls": [
                    {
                        "call_id": "CALL-1",
                        "name": "run_command",
                        "arguments": '{"command":"pytest --version"}',
                    }
                ]
            },
            "This response must not be requested after terminal verification.",
        ]
    )
    agent = DeveloperAgent(llm=llm)
    task = Task(
        id="TASK-FAST-PATH-001",
        title="Terminal verification fast path",
        description="Run the verification command and finish when it succeeds.",
        role="developer",
    )

    result = agent.run(task)

    assert result.status == "completed"
    assert len(llm.tool_call_turns) == 1
    assert result.data["tool_loop_decision"] == {
        "reason": "terminal_verification",
        "skip_llm_turn": True,
        "terminal": True,
    }
    assert result.data["tests"]
    assert result.data["tests"][0]["command"] == "pytest --version"
