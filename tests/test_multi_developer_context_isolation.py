from runtime.context_builder import ContextBuilder
from runtime.task import Task


def _tasks():
    dependency = Task(
        id="DEP-001",
        title="Dependency",
        description="dependency",
        role="developer",
        status="completed",
        result={"files": ["shared.py"], "nested": {"value": 1}},
    )
    task_a = Task(
        id="TASK-A",
        title="Task A",
        description="A",
        role="developer",
        status="ready",
        dependencies=["DEP-001"],
        result={"files": ["a.py"]},
        test_result={"status": "passed", "details": {"count": 1}},
        review_result={"status": "approved", "notes": ["ok"]},
        status_history=[{"status": "ready"}],
        test_history=[{"status": "passed"}],
        review_history=[{"status": "approved"}],
        context={"metadata_value": {"owner": "developer-a"}},
    )
    task_b = Task(
        id="TASK-B",
        title="Task B",
        description="B",
        role="developer",
        status="ready",
        dependencies=["DEP-001"],
        result={"files": ["b.py"]},
        test_result={"status": "passed", "details": {"count": 2}},
        review_result={"status": "revision", "notes": ["fix"]},
        status_history=[{"status": "ready"}],
        test_history=[{"status": "passed"}],
        review_history=[{"status": "revision"}],
        context={"metadata_value": {"owner": "developer-b"}},
    )
    return {task.id: task for task in (dependency, task_a, task_b)}


def test_context_snapshots_are_independent_between_developers():
    tasks = _tasks()
    builder = ContextBuilder(tasks)

    context_a = builder.build_agent_context(tasks["TASK-A"], role="developer")
    context_b = builder.build_agent_context(tasks["TASK-B"], role="developer")

    assert context_a.task_id != context_b.task_id
    assert context_a.dependency_context is not context_b.dependency_context
    assert context_a.history is not context_b.history
    assert context_a.test_history is not context_b.test_history
    assert context_a.review_history is not context_b.review_history
    assert context_a.metadata is not context_b.metadata

    context_a.dependency_context["DEP-001"]["result"]["nested"]["value"] = 99
    context_a.task_result["files"].append("only-a.py")
    context_a.tester_feedback["details"]["count"] = 999
    context_a.reviewer_feedback["notes"].append("only-a")
    context_a.history.append({"status": "mutated-a"})
    context_a.metadata["metadata_value"]["owner"] = "mutated-a"

    assert context_b.dependency_context["DEP-001"]["result"]["nested"]["value"] == 1
    assert context_b.task_result["files"] == ["b.py"]
    assert context_b.tester_feedback["details"]["count"] == 2
    assert context_b.reviewer_feedback["notes"] == ["fix"]
    assert context_b.history == [{"status": "ready"}]
    assert context_b.metadata["metadata_value"]["owner"] == "developer-b"


def test_context_snapshot_is_detached_from_task_mutations():
    tasks = _tasks()
    builder = ContextBuilder(tasks)
    context = builder.build_agent_context(tasks["TASK-A"], role="developer")

    tasks["TASK-A"].result["files"].append("task-mutated.py")
    tasks["TASK-A"].test_result["details"]["count"] = 100
    tasks["TASK-A"].context["metadata_value"]["owner"] = "task-mutated"

    assert context.task_result["files"] == ["a.py"]
    assert context.tester_feedback["details"]["count"] == 1
    assert context.metadata["metadata_value"]["owner"] == "developer-a"


def test_context_to_dict_is_detached_from_context_objects():
    tasks = _tasks()
    context = ContextBuilder(tasks).build_agent_context(tasks["TASK-A"], role="developer")
    payload = context.to_dict()

    payload["task_result"]["files"].append("payload-only.py")
    payload["dependency_context"]["DEP-001"]["result"]["nested"]["value"] = 77
    payload["metadata"]["metadata_value"]["owner"] = "payload-only"

    assert context.task_result["files"] == ["a.py"]
    assert context.dependency_context["DEP-001"]["result"]["nested"]["value"] == 1
    assert context.metadata["metadata_value"]["owner"] == "developer-a"
