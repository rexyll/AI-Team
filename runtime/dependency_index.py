from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DependencyIndex:
    """Immutable indexes derived from a dependency graph."""

    dependencies: dict[str, tuple[str, ...]]
    dependents: dict[str, tuple[str, ...]]

    @classmethod
    def build(cls, graph: dict[str, list[str]]) -> "DependencyIndex":
        dependencies = {
            task_id: tuple(task_dependencies)
            for task_id, task_dependencies in graph.items()
        }
        dependents_mutable: dict[str, list[str]] = {
            task_id: [] for task_id in graph
        }
        for task_id, task_dependencies in graph.items():
            for dependency in task_dependencies:
                if dependency not in graph:
                    raise ValueError(
                        f"Task {task_id} depends on unknown task {dependency}"
                    )
                dependents_mutable[dependency].append(task_id)

        dependents = {
            task_id: tuple(task_dependents)
            for task_id, task_dependents in dependents_mutable.items()
        }
        return cls(dependencies=dependencies, dependents=dependents)

    def dependencies_of(self, task_id: str) -> tuple[str, ...]:
        try:
            return self.dependencies[task_id]
        except KeyError as exc:
            raise KeyError(f"Unknown task id: {task_id}") from exc

    def dependents_of(self, task_id: str) -> tuple[str, ...]:
        try:
            return self.dependents[task_id]
        except KeyError as exc:
            raise KeyError(f"Unknown task id: {task_id}") from exc

    def affected_tasks(self, task_ids: set[str]) -> set[str]:
        """Return selected tasks and all transitive dependents."""
        if not isinstance(task_ids, set):
            raise TypeError("task_ids must be a set")
        unknown = task_ids - self.dependencies.keys()
        if unknown:
            raise ValueError("Unknown task ids: " + ", ".join(sorted(unknown)))

        affected: set[str] = set()
        stack = list(task_ids)
        while stack:
            task_id = stack.pop()
            if task_id in affected:
                continue
            affected.add(task_id)
            stack.extend(self.dependents[task_id])
        return affected
