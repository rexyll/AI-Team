from runtime.agent_result import AgentResult


def normalize_agent_result(
    result,
    *,
    expected_agent: str | None = None,
    expected_task_id: str | None = None,
) -> AgentResult:
    """Normalize an Agent result and optionally validate its execution identity.

    ``expected_agent`` and ``expected_task_id`` are optional so existing
    callers keep their legacy behavior. Runtime orchestration code can provide
    them at stage boundaries to reject results produced for a different Agent
    or task.
    """
    if isinstance(result, AgentResult):
        normalized = result
    elif isinstance(result, dict):
        normalized = AgentResult.from_dict(result)
    else:
        raise TypeError(
            f"Unsupported agent result type: "
            f"{type(result).__name__}"
        )

    if expected_agent is not None:
        if not isinstance(expected_agent, str) or not expected_agent.strip():
            raise ValueError("expected_agent must be a non-empty string")
        expected_agent = expected_agent.strip()
        if normalized.agent != expected_agent:
            raise ValueError(
                "Agent result role mismatch: "
                f"expected '{expected_agent}', got '{normalized.agent}'"
            )

    if expected_task_id is not None:
        if not isinstance(expected_task_id, str) or not expected_task_id.strip():
            raise ValueError("expected_task_id must be a non-empty string")
        expected_task_id = expected_task_id.strip()
        if normalized.task_id != expected_task_id:
            raise ValueError(
                "Agent result task mismatch: "
                f"expected '{expected_task_id}', got '{normalized.task_id}'"
            )

    return normalized
