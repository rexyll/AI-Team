"""Deterministic change-impact analysis for incremental re-execution.

A persisted project that receives a change request must not silently re-run
every task: only tasks whose work is genuinely affected should be executed
again, while unaffected tasks keep their completed state, results and test
evidence. This module implements that decision as a pure, deterministic
function over the old and the re-planned task graphs - no LLM is involved.

Matching is deliberately conservative:

* a task is recognised when it keeps its plan id or its normalised title,
  and its role is unchanged;
* completed evidence is reused only when the title, the description and the
  (id-mapped) dependency set are all unchanged;
* anything that cannot be matched is treated as new work and re-executed;
* tasks downstream of an affected task are re-executed transitively.

Removed tasks are dropped from the graph (a persisted project cannot keep
completed history that is no longer part of the plan) and reported honestly
in the revision report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from runtime.task import Task
from runtime.task_manager import TaskManager

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[，。、；：！？（）【】《》「」『』,.;:!?()\[\]{}<>\"'`~·/\\|]+")

# Statuses that are meaningful to carry over from the old graph. Anything
# else (running / reviewing / revision) is stale execution state left by an
# interrupted run and is normalised back to "pending" so the scheduler can
# pick it up again.
_CARRIED_STATUSES = {"pending", "ready", "completed", "failed", "blocked"}

MARKER_REUSED = "reused"
MARKER_AFFECTED = "affected"
MARKER_NEW = "new"
MARKER_PENDING = "pending"


def normalize_task_text(value: str) -> str:
    """Fold a task title/description into a comparison-stable form."""
    if not isinstance(value, str):
        raise TypeError("task text must be a string")
    folded = _PUNCTUATION.sub(" ", value.casefold())
    return _WHITESPACE.sub(" ", folded).strip()


@dataclass(frozen=True)
class IncrementalRevision:
    """Result of merging a re-planned task graph into a persisted one."""

    tasks: tuple[Task, ...]
    reused_task_ids: tuple[str, ...] = ()
    affected_task_ids: tuple[str, ...] = ()
    added_task_ids: tuple[str, ...] = ()
    carried_task_ids: tuple[str, ...] = ()
    removed_task_ids: tuple[str, ...] = ()
    removed_completed_task_ids: tuple[str, ...] = ()
    reset_completed_task_ids: tuple[str, ...] = ()
    match_bases: dict[str, int] = field(default_factory=dict)

    @property
    def mode(self) -> str:
        """``incremental`` when completed evidence is reused, else ``full``."""
        return "incremental" if self.reused_task_ids else "full"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "reused": list(self.reused_task_ids),
            "affected": list(self.affected_task_ids),
            "added": list(self.added_task_ids),
            "carried": list(self.carried_task_ids),
            "removed": list(self.removed_task_ids),
            "removed_completed": list(self.removed_completed_task_ids),
            "reset_completed": list(self.reset_completed_task_ids),
            "match_bases": dict(self.match_bases),
        }


def _match_tasks(
    old_tasks: list[Task],
    new_tasks: list[Task],
) -> tuple[dict[str, tuple[Task, str]], dict[str, int]]:
    """Pair new plan tasks with old tasks by plan id, then by title."""
    consumed: set[str] = set()
    pairs: dict[str, tuple[Task, str]] = {}
    bases: dict[str, int] = {}

    for basis in ("id", "title"):
        for new_task in new_tasks:
            if new_task.id in pairs:
                continue
            for old_task in old_tasks:
                if old_task.id in consumed or old_task.role != new_task.role:
                    continue
                if basis == "id" and old_task.id != new_task.id:
                    continue
                if basis == "title" and (
                    normalize_task_text(old_task.title) != normalize_task_text(new_task.title)
                ):
                    continue
                pairs[new_task.id] = (old_task, basis)
                consumed.add(old_task.id)
                bases[basis] = bases.get(basis, 0) + 1
                break

    return pairs, bases


def _normalized_dependencies(task: Task, id_map: dict[str, str]) -> tuple[str, ...]:
    """Map old dependency ids onto the re-planned ids for comparison."""
    return tuple(id_map.get(dependency, dependency) for dependency in task.dependencies)


def _carry_state(
    new_task: Task,
    old_task: Task,
    marker: str,
    *,
    status: str | None = None,
) -> Task:
    """Copy durable execution state from an old task onto its new skeleton."""
    new_task.status = status if status is not None else old_task.status
    new_task.status_history = list(old_task.status_history)
    new_task.error = old_task.error
    new_task.review_round = old_task.review_round
    new_task.result = dict(old_task.result)
    new_task.context = {**new_task.context, **dict(old_task.context)}
    new_task.review_result = dict(old_task.review_result)
    new_task.review_history = list(old_task.review_history)
    new_task.test_result = dict(old_task.test_result)
    new_task.test_history = list(old_task.test_history)
    new_task.retry_attempt = old_task.retry_attempt
    new_task.max_retries = old_task.max_retries
    new_task.retry_history = list(old_task.retry_history)
    new_task.context["incremental_revision"] = marker
    return new_task


def build_incremental_revision(
    old_task_manager: TaskManager,
    new_tasks: list[Task] | tuple[Task, ...],
) -> IncrementalRevision:
    """Merge a re-planned graph into the persisted graph, reusing evidence.

    Args:
        old_task_manager: persisted task manager of the previous revision.
        new_tasks: fresh ``pending`` tasks built from the re-planned graph.

    Returns:
        An :class:`IncrementalRevision` whose ``tasks`` are ordered like
        ``new_tasks`` and whose report lists what happened to each task.
    """
    if not isinstance(old_task_manager, TaskManager):
        raise TypeError("old_task_manager must be a TaskManager")
    if not isinstance(new_tasks, (list, tuple)):
        raise TypeError("new_tasks must be a list or tuple")
    if not all(isinstance(task, Task) for task in new_tasks):
        raise TypeError("all new tasks must be Task instances")
    if not new_tasks:
        raise ValueError("new_tasks cannot be empty")

    old_tasks = old_task_manager.get_all_tasks()
    pairs, match_bases = _match_tasks(old_tasks, list(new_tasks))
    id_map = {old.id: new_id for new_id, (old, _basis) in pairs.items()}

    removed = [old for old in old_tasks if old.id not in id_map]

    changed: set[str] = set()
    added: list[str] = []
    changed_old_by_new: dict[str, Task] = {}

    for new_task in new_tasks:
        pair = pairs.get(new_task.id)
        if pair is None:
            added.append(new_task.id)
            changed.add(new_task.id)
            new_task.context["incremental_revision"] = MARKER_NEW
            continue
        old_task, _basis = pair
        changed_old_by_new[new_task.id] = old_task
        text_unchanged = (
            normalize_task_text(old_task.title) == normalize_task_text(new_task.title)
            and normalize_task_text(old_task.description)
            == normalize_task_text(new_task.description)
        )
        dependencies_unchanged = (
            _normalized_dependencies(old_task, id_map) == tuple(new_task.dependencies)
        )
        if not text_unchanged or not dependencies_unchanged:
            changed.add(new_task.id)

    # Downstream propagation: a completed task that depends on re-executed
    # work cannot keep its evidence. Iterate to a fixed point over the DAG;
    # dependency order is not required because the loop is idempotent.
    dependencies_by_task = {task.id: list(task.dependencies) for task in new_tasks}
    while True:
        impacted = {
            task_id
            for task_id, dependencies in dependencies_by_task.items()
            if any(dependency in changed for dependency in dependencies)
        }
        if impacted <= changed:
            break
        changed |= impacted

    merged: list[Task] = []
    reused_ids: list[str] = []
    affected_ids: list[str] = []
    carried_ids: list[str] = []
    reset_completed: list[str] = []

    for new_task in new_tasks:
        if new_task.id in changed:
            old_task = changed_old_by_new.get(new_task.id)
            if old_task is not None and old_task.status == "completed":
                reset_completed.append(new_task.id)
            new_task.context["incremental_revision"] = (
                MARKER_NEW if new_task.id in added else MARKER_AFFECTED
            )
            affected_ids.append(new_task.id)
            merged.append(new_task)
            continue

        old_task = changed_old_by_new[new_task.id]
        if old_task.status == "completed":
            _carry_state(new_task, old_task, MARKER_REUSED)
            new_task.status_history.append(
                {
                    "from": "completed",
                    "to": "completed",
                    "reason": "增量续跑：变更请求未影响该任务，保留完成证据",
                    "incremental_reuse": True,
                }
            )
            reused_ids.append(new_task.id)
        else:
            status = old_task.status
            if status not in _CARRIED_STATUSES:
                status = "pending"
            _carry_state(new_task, old_task, MARKER_PENDING, status=status)
            if old_task.status != status:
                new_task.status_history.append(
                    {
                        "from": old_task.status,
                        "to": status,
                        "reason": "增量续跑：重置中断遗留的非终态状态",
                    }
                )
            carried_ids.append(new_task.id)
        merged.append(new_task)

    removed_completed = tuple(
        old.id for old in removed if old.status == "completed"
    )
    # Removed tasks are dropped: persistence validates that the plan and the
    # task identity set match exactly, and ProjectResult treats cancelled
    # tasks as unfinished, which would misreport the delivery.

    return IncrementalRevision(
        tasks=tuple(merged),
        reused_task_ids=tuple(reused_ids),
        affected_task_ids=tuple(affected_ids),
        added_task_ids=tuple(added),
        carried_task_ids=tuple(carried_ids),
        removed_task_ids=tuple(old.id for old in removed),
        removed_completed_task_ids=removed_completed,
        reset_completed_task_ids=tuple(reset_completed),
        match_bases=match_bases,
    )
