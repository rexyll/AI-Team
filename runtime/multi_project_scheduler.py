from __future__ import annotations

from dataclasses import dataclass

from runtime.project_scheduler import ProjectAdmissionDecision, ProjectExecutionScope, ProjectScheduler


@dataclass(frozen=True)
class ProjectSchedulingRequest:
    """A host-owned scheduling request scoped to one project and task."""

    scope: ProjectExecutionScope
    task_id: str


class MultiProjectScheduler:
    """Coordinate deterministic admission across isolated project schedulers.

    Project-local dependency and resource semantics remain owned by
    ``ProjectScheduler``. This coordinator only selects which already-admissible
    project/task pair should be considered next; it never mutates task state.
    """

    def __init__(self, schedulers: list[ProjectScheduler]) -> None:
        if not isinstance(schedulers, list):
            raise TypeError("schedulers must be a list")
        if any(not isinstance(item, ProjectScheduler) for item in schedulers):
            raise TypeError("all schedulers must be ProjectScheduler instances")
        self._schedulers = {item.scope.project_id: item for item in schedulers}
        if len(self._schedulers) != len(schedulers):
            raise ValueError("Duplicate project scope")

    @property
    def project_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._schedulers))

    def scheduler_for(self, project_id: str) -> ProjectScheduler:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        try:
            return self._schedulers[project_id.strip()]
        except KeyError as exc:
            raise KeyError(f"Unknown project: {project_id}") from exc

    def next_admissible(self) -> ProjectSchedulingRequest | None:
        """Return the lexicographically deterministic next admissible task."""
        candidates: list[ProjectSchedulingRequest] = []
        for project_id in self.project_ids:
            scheduler = self._schedulers[project_id]
            for task in scheduler.admissible_tasks():
                candidates.append(ProjectSchedulingRequest(scheduler.scope, task.id))
        if not candidates:
            return None
        return min(candidates, key=lambda item: (item.scope.project_id, item.task_id))

    def _scheduler_for_task(self, task_id: str) -> ProjectScheduler | None:
        for project_id in self.project_ids:
            scheduler = self._schedulers[project_id]
            try:
                scheduler.decide(task_id)
            except KeyError:
                continue
            return scheduler
        return None

    def decide(self, request: ProjectSchedulingRequest) -> ProjectAdmissionDecision:
        if not isinstance(request, ProjectSchedulingRequest):
            raise TypeError("request must be a ProjectSchedulingRequest")

        scheduler = self._scheduler_for_task(request.task_id)
        if scheduler is not None:
            if request.scope != scheduler.scope:
                raise ValueError("request scope does not match registered project scope")
            return scheduler.decide(request.task_id)

        # Preserve a distinct error for an unknown project when the task itself
        # is not known to any registered project.
        self.scheduler_for(request.scope.project_id)
        raise KeyError(f"Unknown task id: {request.task_id}")
