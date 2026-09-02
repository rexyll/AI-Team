from pathlib import Path

from agents.developer import DeveloperAgent
from runtime.llm.mock import MockLLM
from runtime.task import Task
from security.workspace import get_default_workspace_root, set_default_workspace_root


def test_developer_terminal_verification_fast_path_avoids_followup_llm_turn() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    previous_workspace_root = get_default_workspace_root()
    set_default_workspace_root(repository_root)
    artifact = repository_root / "runtime" / "_fast_path_test_artifact.txt"

    try:
        llm = MockLLM(
            tool_script=[
                {
                    "tool_calls": [
                        {
                            "call_id": "CALL-1",
                            "name": "write_file",
                            "arguments": '{"path":"runtime/_fast_path_test_artifact.txt","content":"terminal verification fixture\\n"}',
                        },
                        {
                            "call_id": "CALL-2",
                            "name": "run_command",
                            "arguments": '{"command":"pytest -q"}',
                        },
                    ]
                },
                "This response must not be requested after terminal verification.",
            ]
        )
        agent = DeveloperAgent(llm=llm)
        task = Task(
            id="TASK-FAST-PATH-001",
            title="Terminal verification fast path",
            description="Make a small workspace change, run the verification command, and finish when it succeeds.",
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
        assert result.data["tests"][0]["command"] == "pytest -q"
    finally:
        if artifact.exists():
            artifact.unlink()
        set_default_workspace_root(previous_workspace_root)
