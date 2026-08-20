from agents.architect import ArchitectAgent
from runtime.agent_context import AgentContext
from runtime.agent_result import AgentResult
from runtime.task import Task


def make_task(**kwargs):
    defaults = {
        "id": "TASK-001",
        "title": "数据库 Schema 设计",
        "description": "设计个人记账软件数据库 Schema",
        "role": "architect",
        "status": "running",
    }

    defaults.update(kwargs)

    return Task(**defaults)


def test_architect_builds_agent_context():
    task = make_task()

    agent = ArchitectAgent()

    context = agent.build_context(task)

    assert isinstance(context, AgentContext)

    assert context.task_id == task.id
    assert context.task_title == task.title
    assert context.task_description == task.description
    assert context.role == "architect"
    assert context.status == task.status


def test_architect_prompt_consumes_agent_context():
    task = make_task(
        id="TASK-ARCH-001",
        title="SQLite Schema",
        description="Design SQLite database schema",
    )

    agent = ArchitectAgent()

    context = AgentContext(
        task_id="TASK-ARCH-001",
        task_title="SQLite Schema",
        task_description="Design SQLite database schema",
        role="architect",
        status="running",
        review_round=2,
        dependencies=[
            "TASK-001",
            "TASK-002",
        ],
        task_result={
            "previous": "result",
        },
        tester_feedback={
            "status": "passed",
        },
        reviewer_feedback={
            "status": "revision",
            "message": "Improve transaction design",
        },
        history=[
            {
                "status": "running",
            },
        ],
        metadata={
            "project_name": "AI-Team",
        },
    )

    messages = agent._build_messages(context)

    assert len(messages) == 2

    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"

    prompt = messages[1]["content"]

    assert "TASK-ARCH-001" in prompt
    assert "SQLite Schema" in prompt
    assert "Design SQLite database schema" in prompt
    assert "architect" in prompt
    assert "running" in prompt
    assert "TASK-001" in prompt
    assert "TASK-002" in prompt
    assert "previous" in prompt

    # Architect must not receive execution feedback or review results.
    assert "passed" not in prompt
    assert "revision" not in prompt
    assert "Improve transaction design" not in prompt
    assert "AI-Team" in prompt


def test_architect_run_returns_agent_result(monkeypatch):
    task = make_task()

    agent = ArchitectAgent()

    def fake_ask_ai(*, prompt, system_prompt):
        assert "数据库 Schema 设计" in prompt
        assert system_prompt
        return "SQLite architecture"

    monkeypatch.setattr(
        "agents.architect.ask_ai",
        fake_ask_ai,
    )

    result = agent.run(task)

    assert isinstance(result, AgentResult)

    assert result.status == "completed"
    assert result.agent == "architect"
    assert result.task_id == task.id
    assert result.message == "SQLite architecture"

    assert result.data == {
        "architecture": "SQLite architecture",
    }


def test_architect_run_does_not_mutate_task(monkeypatch):
    task = make_task()

    task.context = {
        "project_name": "AI-Team",
    }

    task.result = {
        "existing": {
            "value": 1,
        },
    }

    original_context = {
        "project_name": "AI-Team",
    }

    original_result = {
        "existing": {
            "value": 1,
        },
    }

    agent = ArchitectAgent()

    def fake_ask_ai(*, prompt, system_prompt):
        return "architecture"

    monkeypatch.setattr(
        "agents.architect.ask_ai",
        fake_ask_ai,
    )

    agent.run(task)

    assert task.context == original_context
    assert task.result == original_result


def test_architect_run_rejects_non_task():
    agent = ArchitectAgent()

    try:
        agent.run("not-a-task")
    except TypeError as exc:
        assert "ArchitectAgent.run() expects Task" in str(exc)
    else:
        raise AssertionError(
            "ArchitectAgent.run() should reject non-Task input"
        )