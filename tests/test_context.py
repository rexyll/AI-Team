from agents.architect import ArchitectAgent
from runtime.context_builder import build_task_context
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


    architect = ArchitectAgent()


    print()
    print("=" * 60)
    print("RUN ARCHITECT")
    print("=" * 60)

    architect_result = architect.run(architect_task)

    print()
    print("ARCHITECT RETURN VALUE:")
    print(architect_result)

    print()
    print("ARCHITECT RESULT:")
    print(architect_task.result)
    
    # architect_task.status = "completed"


    all_tasks = {
        architect_task.id: architect_task,
        developer_task.id: developer_task,
    }


    context = build_task_context(
        developer_task,
        all_tasks,
    )


    developer_task.context = context


    print()
    print("=" * 60)
    print("DEVELOPER CONTEXT")
    print("=" * 60)

    for task_id, data in context.items():

        print()
        print(f"Dependency: {task_id}")
        print(f"Role: {data['role']}")
        print(f"Title: {data['title']}")

        assert data["result"]["architecture"]
        
        print()
        print("Result:")
        print(
            data["result"]["architecture"]
        )
        