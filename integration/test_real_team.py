from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.agent_factory import create_agent_router
from core.orchestrator import Orchestrator


def main():

    tasks = [
        Task(
            id="TASK-001",
            title="数据库设计",
            description="""
设计一个简单的个人记账软件数据库。

要求：
1. 使用 SQLite
2. 支持收入
3. 支持支出
4. 支持分类
5. 支持交易记录
""",
            role="architect",
        ),
        Task(
            id="TASK-002",
            title="实现数据库模块",
            description="""
根据 Architect 的数据库设计，
实现 SQLite 数据库模块。

要求：
1. 创建数据库
2. 创建数据表
3. 提供基本 CRUD
4. 编写单元测试
""",
            role="developer",
            dependencies=["TASK-001"],
        ),
    ]

    task_manager = TaskManager(tasks)

    router = create_agent_router()

    orchestrator = Orchestrator(
        task_manager=task_manager,
        agent_router=router,
    )

    orchestrator.run()

    print()
    print("=" * 60)
    print("FINAL TASK STATUS")
    print("=" * 60)

    for task in task_manager.get_all_tasks():

        print(
            f"{task.id:<10}"
            f"{task.status:<12}"
            f"{task.role:<12}"
            f"{task.title}"
        )


if __name__ == "__main__":
    main()