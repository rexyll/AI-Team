from runtime.agent_result import AgentResult
from runtime.task import Task


def normalize_agent_result(result) -> AgentResult:
    if isinstance(result, AgentResult):
        return result

    if isinstance(result, dict):
        return AgentResult.from_dict(result)

    raise TypeError(
        f"Unsupported agent result type: "
        f"{type(result).__name__}"
    )
    
def _normalize_developer_result(
    self,
    result,
    task: Task,
):
    if isinstance(result, dict):
        result = dict(result)

        result.setdefault(
            "agent",
            "developer",
        )

        result.setdefault(
            "task_id",
            task.id,
        )

    return normalize_agent_result(result)