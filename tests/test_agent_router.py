from agents.mock_agents import MockAgent
from runtime.agent_router import AgentRouter
from runtime.task import Task


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


tasks = [
    Task(
        id="TASK-001",
        title="数据库设计",
        description="设计数据库",
        role="architect",
    ),
    Task(
        id="TASK-002",
        title="实现 API",
        description="实现 API",
        role="developer",
    ),
    Task(
        id="TASK-003",
        title="编写测试",
        description="编写测试",
        role="tester",
    ),
    Task(
        id="TASK-004",
        title="代码审查",
        description="审查代码",
        role="reviewer",
    ),
]


print()
print("=" * 60)
print("AGENT ROUTER TEST")
print("=" * 60)


for task in tasks:

    agent = router.get_agent(task.role)

    print(
        f"{task.id:<10}"
        f"{task.role:<12}"
        f"-> "
        f"{agent.__class__.__name__}"
    )

    result = agent.run(task)

    print(
        f"    result: {result}"
    )