from agents.architect import ArchitectAgent
from runtime.context_builder import build_task_context
from runtime.llm.mock import MockLLM
from runtime.task import Task


def test_architect_context():
    architect_task = Task(
        id="TASK-001",
        title="数据库 Schema 设计",
        description="""
    设计个人记账软件的 SQLite 数据库。
    """,
        role="architect",
    )

    developer_task = Task(
        id="TASK-003",
        title="后端数据模型与 DAO 层开发",
        description="""
    根据数据库设计实现数据模型和 DAO 层。
    """,
        role="developer",
        dependencies=["TASK-001"],
    )

    architect = ArchitectAgent(
        llm=MockLLM("SQLite architecture"),
    )

    architect_result = architect.run(architect_task)

    assert architect_result.data["architecture"] == "SQLite architecture"

    all_tasks = {
        architect_task.id: architect_task,
        developer_task.id: developer_task,
    }

    context = build_task_context(
        developer_task,
        all_tasks,
    )

    developer_task.context = context

    for task_id, data in context.items():
        assert task_id == "TASK-001"
        assert data["role"] == "architect"
        assert data["title"] == "数据库 Schema 设计"
        assert data["result"]["architecture"] == "SQLite architecture"
