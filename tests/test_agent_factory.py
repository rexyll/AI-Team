from runtime.agent_factory import create_agent_router


def test_agent_factory_registers_all_agents():
    router = create_agent_router()

    assert router.get_agent("architect") is not None
    assert router.get_agent("developer") is not None
    assert router.get_agent("tester") is not None
    assert router.get_agent("reviewer") is not None
