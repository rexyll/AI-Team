from runtime.agent_result import AgentResult
from runtime.llm.base import BaseLLM
from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord

from benchmarks.real_developer.executor import DeveloperAgentExecutor


class _NoOpLLM(BaseLLM):
    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        return "ok"

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        raise AssertionError("the fake agent should replace run()")


def _executor(task: Task) -> tuple[DeveloperAgentExecutor, TaskManager]:
    manager = TaskManager([task])
    executor = DeveloperAgentExecutor(
        manager,
        1,
        llm_factory=_NoOpLLM,
    )
    return executor, manager


def _record(task_id: str) -> ToolExecutionRecord:
    return ToolExecutionRecord(
        execution_id="call-1",
        task_id=task_id,
        agent_role="developer",
        tool_name="read_file",
        started_at="2026-08-31T10:00:00Z",
        completed_at="2026-08-31T10:00:01Z",
        status="completed",
        arguments={"path": "app/utils/helpers.py"},
        output="def paginate(...): pass",
        metadata={
            "execution_id": "call-1",
            "tool_name": "read_file",
            "arguments_hash": "args",
            "result_hash": "result",
            "result_chars": 23,
            "retained_result_chars": 23,
            "result_truncated": False,
            "duplicate_of": None,
            "retry_of": None,
            "category": "exploration",
        },
    )


def test_agent_exception_preserves_partial_tool_telemetry() -> None:
    task = Task("TASK-EXEC-FAIL-001", "failure", "exercise executor failure", "developer", status="ready")
    executor, manager = _executor(task)
    binding = executor._bindings[0]
    binding.agent.tool_execution_history = ToolExecutionHistory()

    def exploding_run(current_task: Task):
        binding.agent.tool_execution_history.append(_record(current_task.id))
        raise RuntimeError("boom")

    binding.agent.run = exploding_run

    metrics = executor.run_task(task, "developer-1")

    assert metrics.failed is True
    assert metrics.failure_stage == "agent_run"
    assert metrics.failure_reason == "RuntimeError: boom"
    assert metrics.tool_calls == 1
    assert metrics.test_commands == 0
    assert metrics.unique_tool_calls == 1
    assert metrics.duplicate_tool_calls == 0
    assert metrics.tool_result_chars == 23
    assert metrics.tool_loop_telemetry[0]["tool_name"] == "read_file"
    assert manager.get_task(task.id).status == "failed"


def test_task_manager_failure_preserves_agent_result_telemetry() -> None:
    task = Task("TASK-EXEC-FAIL-002", "transition", "exercise transition failure", "developer", status="ready")
    executor, manager = _executor(task)
    binding = executor._bindings[0]

    telemetry = {
        "execution_id": "call-2",
        "tool_name": "read_file",
        "arguments_hash": "args-2",
        "result_hash": "result-2",
        "result_chars": 17,
        "retained_result_chars": 17,
        "result_truncated": False,
        "duplicate_of": None,
        "retry_of": None,
        "category": "exploration",
    }
    binding.agent.run = lambda current_task: AgentResult(
        status="completed",
        agent="developer",
        task_id=current_task.id,
        message="done",
        data={
            "validation": {
                "tool_call_count": 1,
                "test_command_count": 0,
                "unique_tool_calls": 1,
                "duplicate_tool_calls": 0,
                "retry_tool_calls": 0,
                "tool_result_chars": 17,
                "largest_tool_result_chars": 17,
            },
            "tool_loop_cache": {"hits": 1, "misses": 1, "invalidations": 0},
            "tool_loop_telemetry": (telemetry,),
            "developer_decision_trace": ({"convergence_reason": "new_evidence_requires_reasoning"},),
        },
    )

    def reject_transition(task_id: str, result: dict):
        raise RuntimeError("transition failed")

    manager.mark_developer_completed = reject_transition

    metrics = executor.run_task(task, "developer-1")

    assert metrics.failed is True
    assert metrics.failure_stage == "task_manager_transition"
    assert metrics.failure_reason == "RuntimeError: transition failed"
    assert metrics.tool_calls == 1
    assert metrics.tool_result_chars == 17
    assert metrics.cache_hits == 1
    assert metrics.developer_decision_trace[0]["convergence_reason"] == "new_evidence_requires_reasoning"


def test_agent_result_failure_diagnostic_is_emitted_without_result_content(capsys, monkeypatch) -> None:
    monkeypatch.setenv("AGNES_REQUEST_DIAGNOSTICS", "1")
    task = Task("TASK-EXEC-FAIL-003", "diagnostic", "exercise diagnostics", "developer", status="ready")
    executor, manager = _executor(task)
    binding = executor._bindings[0]
    telemetry = {
        "tool_name": "run_command",
        "result_chars": 42,
        "duplicate_of": "call-0",
        "retry_of": None,
    }
    binding.agent.run = lambda current_task: AgentResult(
        status="failed",
        agent="developer",
        task_id=current_task.id,
        message="tool_loop_progress_guard: repeated exact tool call",
        data={
            "validation": {
                "tool_call_count": 1,
                "test_command_count": 1,
                "unique_tool_calls": 0,
                "duplicate_tool_calls": 1,
                "retry_tool_calls": 0,
                "tool_result_chars": 42,
                "largest_tool_result_chars": 42,
            },
            "tool_loop_telemetry": (telemetry,),
        },
    )

    metrics = executor.run_task(task, "developer-1")

    assert metrics.failed is True
    assert metrics.failure_stage == "agent_result"
    assert metrics.failure_reason == "tool_loop_progress_guard: repeated exact tool call"
    output = capsys.readouterr().out
    assert "[LLM DIAGNOSTIC]" in output
    assert "stage=agent_result" in output
    assert "task_id=TASK-EXEC-FAIL-003" in output
    assert "developer_id=developer-1" in output
    assert "tool_names=['run_command']" in output
    assert "tool_result_chars=[42]" in output
    assert "repeat" not in output.lower()
    assert "result_chars" in output
    assert manager.get_task(task.id).status == "failed"
