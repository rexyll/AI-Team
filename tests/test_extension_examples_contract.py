from pathlib import Path

from examples.custom_agent import ExampleAgent, build_example_agent
from examples.custom_llm import ExampleLLM, build_example_llm
from examples.custom_tool import build_example_registry
from examples.persistence_query import PROJECT_ID, run_example
from runtime.agent_result import AgentResult
from runtime.task import Task
from runtime.llm.base import BaseLLM


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_README = ROOT / "examples" / "README.md"


def test_custom_agent_example_uses_canonical_result_contract() -> None:
    agent = build_example_agent()
    assert isinstance(agent, ExampleAgent)
    result = agent.run(
        Task(
            id="TASK-EXAMPLE-001",
            title="contract example",
            description="Verify the custom agent example.",
            role="example",
        )
    )
    assert isinstance(result, AgentResult)
    assert result.status == "completed"
    assert result.agent == "example"
    assert result.task_id == "TASK-EXAMPLE-001"


def test_custom_llm_example_implements_provider_boundary() -> None:
    llm = build_example_llm()
    assert isinstance(llm, ExampleLLM)
    assert isinstance(llm, BaseLLM)
    assert llm.generate("hello").startswith("example-response: hello")


def test_custom_tool_example_registers_schema_and_implementation() -> None:
    registry = build_example_registry()
    assert registry.list() == ["summarize_text"]
    assert registry.schema("summarize_text")["function"]["name"] == "summarize_text"
    assert registry.get("summarize_text")(text="hello world") == {"summary": "hello world"}


def test_persistence_query_example_is_read_only_after_save(tmp_path) -> None:
    result = run_example(tmp_path / "events")
    assert result["lifecycle"] == "resumed"
    assert result["last_event"] == (
        "EVENT-EXAMPLE-001",
        "project.resumed",
        "2026-08-22T12:00:00Z",
    )
    assert PROJECT_ID == "PROJECT-EXAMPLE-001"


def test_examples_document_current_safety_and_extension_boundaries() -> None:
    content = EXAMPLES_README.read_text(encoding="utf-8")
    for section in (
        "## Custom Agent",
        "## Custom LLM",
        "## Custom Tool",
        "## Persistence and Query",
        "authorization boundary",
        "workspace sandbox",
    ):
        assert section in content
