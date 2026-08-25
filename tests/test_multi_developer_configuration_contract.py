from agents.developer import DeveloperAgent
from runtime.agent_config import AgentConfig
from runtime.agent_router import AgentRouter


def _developer(name: str, model: str) -> DeveloperAgent:
    return DeveloperAgent(
        AgentConfig(
            role="developer",
            model=model,
            extra={"developer_id": name},
        )
    )


def test_router_registers_multiple_developers():
    first = _developer("developer-1", "model-a")
    second = _developer("developer-2", "model-b")
    third = _developer("developer-3", "model-c")

    router = AgentRouter()
    router.register_developer_pool([first, second, third])

    assert router.get_agent("developer") is first
    assert router.get_developers() == [first, second, third]
    assert router.get_developer_for_task("TASK-001") in {first, second, third}
    assert router.get_developer_for_task("TASK-002") in {first, second, third}


def test_task_assignment_is_stable_for_same_task_id():
    developers = [
        _developer("developer-1", "model-a"),
        _developer("developer-2", "model-b"),
        _developer("developer-3", "model-c"),
    ]
    router = AgentRouter()
    router.register_developer_pool(developers)

    assigned = router.get_developer_for_task("TASK-017")
    assert router.get_developer_for_task("TASK-017") is assigned


def test_empty_developer_pool_is_rejected():
    router = AgentRouter()
    try:
        router.register_developer_pool([])
    except ValueError:
        return
    raise AssertionError("empty developer pool must be rejected")
