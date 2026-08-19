from runtime.agent_result import AgentResult


def normalize_agent_result(result) -> AgentResult:
    if isinstance(result, AgentResult):
        return result

    if isinstance(result, dict):
        return AgentResult.from_dict(result)

    raise TypeError(
        f"Unsupported agent result type: "
        f"{type(result).__name__}"
    )