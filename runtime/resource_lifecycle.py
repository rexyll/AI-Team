from __future__ import annotations

from dataclasses import dataclass

from runtime.resource_governor import ResourceGovernor
from runtime.task import Task


@dataclass(frozen=True)
class ResourceLifecycle:
    """Immutable resource lifecycle for one admitted task."""

    task_id: str
    governor: ResourceGovernor
    active: bool = False

    @classmethod
    def admit(cls, task: Task, governor: ResourceGovernor) -> "ResourceLifecycle | None":
        if not isinstance(task, Task):
            raise TypeError("task must be a Task")
        if not isinstance(governor, ResourceGovernor):
            raise TypeError("governor must be a ResourceGovernor")
        snapshot = governor.start_task()
        return cls(task.id, snapshot, True)

    def consume(self, *, tool_calls: int = 0, input_tokens: int = 0, output_tokens: int = 0) -> "ResourceLifecycle":
        if not self.active:
            raise RuntimeError("resource lifecycle is not active")
        return ResourceLifecycle(
            self.task_id,
            self.governor.consume(
                tool_calls=tool_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            True,
        )

    def finish(self) -> "ResourceLifecycle":
        if not self.active:
            return self
        return ResourceLifecycle(self.task_id, self.governor.finish_task(), False)
