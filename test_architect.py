from agents.architect import ArchitectAgent
from runtime.task import Task

def test_architect_agent():
    

    task = Task(
        id="TASK-001",
        title="数据库 Schema 设计",
        description="""
    设计个人记账软件的 SQLite 数据库。

    要求：

    1. 支持收入和支出
    2. 支持分类
    3. 支持按月份统计
    4. 支持后续 REST API 查询
    5. 数据结构应该方便扩展
    """,
        role="architect",
    )


    agent = ArchitectAgent()


    print()
    print("=" * 60)
    print("ARCHITECT AGENT TEST")
    print("=" * 60)

    print()
    print("Task:")
    print(task.title)

    print()
    print("Calling Architect Agent...")

    result = agent.run(task)

    assert result["status"] == "completed"
    assert result["agent"] == "architect"
    assert result["task_id"] == task.id
    assert "architecture" in result
    assert result["architecture"]

    print()
    print("=" * 60)
    print("ARCHITECT RESULT")
    print("=" * 60)

    print(result["architecture"])