from runtime.llm.base import BaseLLM, LLMResponse, LLMToolCall
from runtime.task import Task
from runtime.task_manager import TaskManager

from benchmarks.real_developer.executor import DeveloperAgentExecutor


class _DeterministicAgentLLM(BaseLLM):
    def __init__(self):
        self.calls = 0

    def generate(self, prompt, *, system_prompt="", temperature=0.2, max_tokens=4096):
        return "ok"

    def generate_with_tools(self, messages, *, tools=None, tool_choice="auto"):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content=None,
                tool_calls=(
                    LLMToolCall(
                        call_id="call-1",
                        name="list_files",
                        arguments='{"path":"."}',
                    ),
                ),
                usage={"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            )
        return LLMResponse(
            content="completed",
            usage={"prompt_tokens": 25, "completion_tokens": 8, "total_tokens": 33},
        )


def test_developer_agent_executor_collects_real_agent_llm_metrics():
    task = Task(
        "TASK-REAL-001",
        "Instrumented Developer",
        "Exercise DeveloperAgent through an injected LLM",
        "developer",
        status="ready",
    )
    manager = TaskManager([task])
    created = []

    def llm_factory():
        llm = _DeterministicAgentLLM()
        created.append(llm)
        return llm

    executor = DeveloperAgentExecutor(
        manager,
        1,
        llm_factory=llm_factory,
    )

    metrics = executor.run_task(task, "developer-1")

    assert metrics.failed is False
    assert metrics.llm_calls == 2
    assert metrics.input_tokens == 45
    assert metrics.output_tokens == 13
    assert manager.get_task(task.id).status == "review_pending"
    assert created[0].calls == 2
