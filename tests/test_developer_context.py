from agents.developer import DeveloperAgent
from runtime.agent_context import AgentContext


def make_context() -> AgentContext:
    return AgentContext(
        task_id="TASK-002",
        task_title="实现记账服务",
        task_description="实现记账服务核心逻辑",
        role="developer",
        status="running",
        dependencies=["TASK-001"],
        dependency_context={
            "TASK-001": {
                "title": "架构设计",
                "role": "architect",
                "result": {
                    "architecture": "使用 SQLite + repository layer",
                },
            }
        },
        task_result={
            "previous": "implementation attempt",
        },
        tester_feedback={
            "status": "failed",
            "message": "missing validation",
        },
        reviewer_feedback={
            "status": "revision",
            "message": "improve error handling",
        },
        review_round=1,
        history=[
            {
                "status": "review_pending",
            }
        ],
        metadata={
            "source": "workflow",
        },
    )


def test_developer_build_messages_consumes_agent_context():
    agent = DeveloperAgent()
    messages = agent._build_messages(make_context())

    prompt = messages[1]["content"]

    assert "TASK-002" in prompt
    assert "实现记账服务" in prompt
    assert "实现记账服务核心逻辑" in prompt
    assert "TASK-001" in prompt
    assert "使用 SQLite + repository layer" in prompt
    assert "missing validation" in prompt
    assert "improve error handling" in prompt
    assert "Review Round:" in prompt
    assert "Execution History:" in prompt
    assert "Metadata:" in prompt


def test_developer_build_messages_does_not_require_task_context():
    context = AgentContext(
        task_id="TASK-001",
        task_title="demo",
        task_description="demo description",
        role="developer",
        status="running",
    )

    messages = DeveloperAgent()._build_messages(context)

    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "TASK-001" in messages[1]["content"]
