from agents.mock_agents import MockAgent
from core.orchestrator import Orchestrator
from runtime.agent_router import AgentRouter
from runtime.task import Task
from runtime.task_manager import TaskManager


def test_orchestrator_agent():

    tasks = [
        Task(
            id="TASK-001",
            title="数据库设计",
            description="设计 SQLite 数据库结构",
            role="architect",
        ),
        Task(
            id="TASK-002",
            title="后端开发",
            description="实现后端数据访问层",
            role="developer",
            dependencies=["TASK-001"],
        ),
        Task(
            id="TASK-003",
            title="测试",
            description="执行自动化测试",
            role="tester",
            dependencies=["TASK-002"],
        ),
        Task(
            id="TASK-004",
            title="代码审查",
            description="审查项目代码",
            role="reviewer",
            dependencies=["TASK-003"],
        ),
    ]

    task_manager = TaskManager(tasks)

    router = AgentRouter()

    router.register(
        "architect",
        MockAgent("architect"),
    )

    router.register(
        "developer",
        MockAgent("developer"),
    )

    router.register(
        "tester",
        MockAgent("tester"),
    )

    router.register(
        "reviewer",
        MockAgent("reviewer"),
    )

    orchestrator = Orchestrator(
        task_manager,
        router,
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
