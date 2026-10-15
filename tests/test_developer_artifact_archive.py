from __future__ import annotations

from datetime import datetime, timezone

from agents.developer import DeveloperAgent
from runtime.agent_config import AgentConfig
from runtime.artifact_store import FilesystemArtifactStore
from runtime.tool_execution_history import ToolExecutionHistory


def _agent(tmp_path, **kwargs) -> DeveloperAgent:
    agent = DeveloperAgent(AgentConfig(role="developer", model=""), **kwargs)
    agent.tool_execution_history = ToolExecutionHistory()
    return agent


def _record(agent, *, output):
    agent._record_tool_execution(
        execution_id="EXEC-1",
        task_id="TASK-1",
        tool_name="run_command",
        started_at=datetime.now(timezone.utc).isoformat(),
        status="completed",
        arguments={"command": "python test_all.py"},
        output=output,
        error=None,
        metadata={"result_hash": "abc"},
    )


def test_large_output_is_archived_and_history_keeps_reference(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    agent = _agent(tmp_path, artifact_store=store)
    large_output = "x" * 20000

    _record(agent, output=large_output)

    record = agent.tool_execution_history.get("EXEC-1")
    assert record.output.startswith("[artifact ")
    assert "sha256=" in record.output
    artifact_id = record.metadata["artifact_id"]
    assert record.metadata["artifact_chars"] == 20000
    assert store.read_text(artifact_id) == large_output
    assert store.get(artifact_id).task_id == "TASK-1"
    assert store.get(artifact_id).metadata["tool_name"] == "run_command"


def test_small_output_is_recorded_verbatim(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    agent = _agent(tmp_path, artifact_store=store)

    _record(agent, output="small result")

    record = agent.tool_execution_history.get("EXEC-1")
    assert record.output == "small result"
    assert "artifact_id" not in record.metadata
    assert store.count() == 0


def test_failed_and_none_outputs_are_never_archived(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    agent = _agent(tmp_path, artifact_store=store)

    agent._record_tool_execution(
        execution_id="EXEC-2",
        task_id="TASK-1",
        tool_name="run_command",
        started_at=datetime.now(timezone.utc).isoformat(),
        status="failed",
        arguments={"command": "python test_all.py"},
        # The real caller passes output=None for failed status.
        output=None,
        error={"type": "RuntimeError", "message": "boom"},
        metadata={},
    )

    record = agent.tool_execution_history.get("EXEC-2")
    assert record.output is None
    assert store.count() == 0


def test_custom_threshold_controls_archiving(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    agent = _agent(tmp_path, artifact_store=store, artifact_min_chars=8)

    _record(agent, output="tiny!!!!!")  # 9 chars, above the threshold of 8

    record = agent.tool_execution_history.get("EXEC-1")
    assert record.output.startswith("[artifact ")
    assert store.read_text(record.metadata["artifact_id"]) == "tiny!!!!!"


def test_without_store_history_keeps_full_output(tmp_path):
    agent = _agent(tmp_path)
    large_output = "z" * 20000

    _record(agent, output=large_output)

    record = agent.tool_execution_history.get("EXEC-1")
    assert record.output == large_output


def test_duplicate_execution_id_is_disambiguated_not_fatal(tmp_path):
    from runtime.tool_execution_record import ToolExecutionRecord

    agent = _agent(tmp_path)

    def make_record(execution_id):
        return ToolExecutionRecord(
            execution_id=execution_id,
            task_id="TASK-1",
            agent_role="developer",
            tool_name="run_command",
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            status="completed",
            arguments={"command": "python test_all.py"},
            output="ok",
            error=None,
            metadata={},
        )

    agent.tool_execution_history.append(make_record("call_abc"))
    # A gate retry can legitimately reuse model-generated call ids.
    agent._record_tool_execution(
        execution_id="call_abc",
        task_id="TASK-1",
        tool_name="run_command",
        started_at=datetime.now(timezone.utc).isoformat(),
        status="completed",
        arguments={"command": "python test_all.py"},
        output="ok from retry",
        error=None,
        metadata={},
    )

    retried = agent.tool_execution_history.get("call_abc#2")
    assert retried.output == "ok from retry"
    assert agent.tool_execution_history.get("call_abc").output == "ok"
