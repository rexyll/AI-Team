from agents.architect import ArchitectAgent
from agents.developer import DeveloperAgent
from agents.reviewer import ReviewerAgent
from agents.tester import TesterAgent

from runtime.agent_router import AgentRouter


def create_agent_router() -> AgentRouter:
    router = AgentRouter()

    router.register("architect", ArchitectAgent())
    router.register("developer", DeveloperAgent())
    router.register("tester", TesterAgent())
    router.register("reviewer", ReviewerAgent())

    return router
