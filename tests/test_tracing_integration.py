from agents.base import BaseAgent
from runtime.agent_result import AgentResult
from runtime.llm.mock import MockLLM
from runtime.task import Task
from runtime.tool_invocation_service import ToolInvocationService
from runtime.tracing import DEFAULT_TRACER


class _TracingAgent(BaseAgent):
    @property
    def role(self) -> str:
        return "developer"

    def run(self, task: Task) -> AgentResult:
        self._generate("hello")
        return AgentResult(
            status="completed",
            agent=self.role,
            task_id=task.id,
            message="done",
        )


def _task() -> Task:
    return Task(
        id="TASK-TRACE-001",
        title="Tracing",
        description="Trace lifecycle",
        role="developer",
        status="running",
    )


def test_agent_run_and_llm_share_trace_lineage_and_task_attributes():
    DEFAULT_TRACER.reset()
    agent = _TracingAgent(llm=MockLLM("ok"))

    result = agent.run(_task())

    assert result.status == "completed"
    records = DEFAULT_TRACER.snapshot()
    assert [item["name"] for item in records] == ["llm.generate", "workflow.stage.developer"]
    stage, llm = records[1], records[0]
    assert stage["attributes"]["task_id"] == "TASK-TRACE-001"
    assert stage["attributes"]["agent_role"] == "developer"
    assert stage["attributes"]["stage"] == "developer"
    assert stage["attributes"]["result.status"] == "completed"
    assert llm["parent_span_id"] == stage["span_id"]
    assert llm["trace_id"] == stage["trace_id"]


def test_tool_invocation_creates_child_span_with_safe_runtime_identity(tmp_path):
    DEFAULT_TRACER.reset()
    target = tmp_path / "trace.txt"
    target.write_text("hello", encoding="utf-8")

    service = ToolInvocationService()
    result = service.invoke(
        role="developer",
        task_id="TASK-TRACE-002",
        execution_id="exec-1",
        tool_name="read_file",
        arguments={"path": str(target)},
    )

    assert result.success is True
    records = DEFAULT_TRACER.snapshot()
    assert len(records) == 1
    span = records[0]
    assert span["name"] == "tool.invoke"
    assert span["status"] == "ok"
    assert span["attributes"]["task_id"] == "TASK-TRACE-002"
    assert span["attributes"]["agent_role"] == "developer"
    assert span["attributes"]["tool_name"] == "read_file"
    assert span["attributes"]["execution_id"] == "exec-1"
    assert span["attributes"].get("output") is None
