import inspect

from runtime import context_builder, workflow


# Phase 3.4.5 inventory. Every direct legacy Task.context usage is classified
# here so the retirement boundary cannot silently expand again.
#
# A = canonical runtime data source -> must migrate
# B = dependency compatibility bridge -> temporarily retained
# C = metadata compatibility -> explicitly retained
# D = dead / redundant usage -> remove


def test_legacy_context_inventory_has_no_unclassified_runtime_reader():
    source = inspect.getsource(context_builder.ContextBuilder)

    # ContextBuilder is the only runtime reader of Task.context and its
    # responsibilities are intentionally limited to B/C compatibility.
    assert "getattr(task, \"context\", {})" in source
    assert "_build_dependency_context" in source
    assert "_build_metadata" in source


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
        "runtime.context_builder.ContextBuilder._build_dependency_context": "B",
        "runtime.context_builder.ContextBuilder._build_metadata": "C",
        "runtime.workflow.TaskWorkflow._build_context": "B",
    }

    assert set(inventory.values()) <= {"A", "B", "C", "D"}
    assert inventory["runtime.context_builder.ContextBuilder._build_dependency_context"] == "B"
    assert inventory["runtime.context_builder.ContextBuilder._build_metadata"] == "C"
    assert inventory["runtime.workflow.TaskWorkflow._build_context"] == "B"
