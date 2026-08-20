import inspect

from runtime import context_builder, workflow
from runtime.legacy_dependency_bridge import LegacyDependencyBridge


# Phase 3.4.6 inventory. Direct Task.context dependency reads are isolated
# inside the compatibility bridge; canonical execution state remains outside
# the legacy bridge.
#
# A = canonical runtime data source -> must migrate
# B = dependency compatibility bridge -> temporarily retained
# C = metadata compatibility -> explicitly retained
# D = dead / redundant usage -> remove


def test_legacy_context_inventory_has_single_dependency_bridge_reader():
    bridge_source = inspect.getsource(LegacyDependencyBridge)

    assert 'getattr(task, "context", {})' in bridge_source
    assert "_legacy_snapshot" in bridge_source
    assert "REQUIRED_KEYS" in bridge_source


def test_context_builder_delegates_dependency_resolution_to_bridge():
    source = inspect.getsource(context_builder.ContextBuilder)

    assert "LegacyDependencyBridge" in source
    assert "self._dependency_bridge.build(task)" in source

    # ContextBuilder may still read Task.context for C-class metadata
    # compatibility, but it must not implement a second dependency bridge.
    assert "task.context.get(dependency_id)" not in source


def test_legacy_context_inventory_workflow_writer_is_dependency_bridge_only():
    source = inspect.getsource(workflow.TaskWorkflow._build_context)

    assert 'task.context["dependencies"]' in source
    assert "build_task_context" in source

    # The workflow must not use legacy Task.context as a source for
    # canonical result, tester, reviewer, or history state.
    assert 'task.context["result"]' not in source
    assert 'task.context["tester_feedback"]' not in source
    assert 'task.context["reviewer_feedback"]' not in source
    assert 'task.context["history"]' not in source
    assert 'task.context["test_history"]' not in source
    assert 'task.context["review_history"]' not in source


def test_legacy_context_inventory_classification_is_explicit():
    inventory = {
        "runtime.legacy_dependency_bridge.LegacyDependencyBridge": "B",
        "runtime.context_builder.ContextBuilder._build_metadata": "C",
        "runtime.workflow.TaskWorkflow._build_context": "B",
    }

    assert set(inventory.values()) <= {"A", "B", "C", "D"}
    assert inventory["runtime.legacy_dependency_bridge.LegacyDependencyBridge"] == "B"
    assert inventory["runtime.context_builder.ContextBuilder._build_metadata"] == "C"
    assert inventory["runtime.workflow.TaskWorkflow._build_context"] == "B"
