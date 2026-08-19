from runtime.context_builder import build_task_context
from runtime.task import Task


def test_build_task_context_includes_completed_dependencies():
    dependency = Task(
        id="TASK-DEP-001",
        title="dependency",
        description="dependency task",
        role="developer",
        status="completed",
        result={
            "status": "completed",
            "message": "dependency done",
        },
    )

    task = Task(
        id="TASK-MAIN-001",
        title="main",
        description="main task",
        role="developer",
        dependencies=["TASK-DEP-001"],
    )

    context = build_task_context(
        task,
        {
            dependency.id: dependency,
            task.id: task,
        },
    )

    assert context["TASK-DEP-001"]["title"] == "dependency"
    assert context["TASK-DEP-001"]["role"] == "developer"
    assert context["TASK-DEP-001"]["result"]["message"] == "dependency done"
    
    
def test_build_task_context_ignores_incomplete_dependencies():
    dependency = Task(
        id="TASK-DEP-001",
        title="dependency",
        description="dependency task",
        role="developer",
        status="running",
        result={
            "status": "completed",
            "message": "not actually finished",
        },
    )

    task = Task(
        id="TASK-MAIN-001",
        title="main",
        description="main task",
        role="developer",
        dependencies=["TASK-DEP-001"],
    )

    context = build_task_context(
        task,
        {
            dependency.id: dependency,
            task.id: task,
        },
    )

    assert context == {}
    
    
def test_build_task_context_ignores_missing_dependencies():
    task = Task(
        id="TASK-MAIN-001",
        title="main",
        description="main task",
        role="developer",
        dependencies=["TASK-NOT-EXIST"],
    )

    context = build_task_context(
        task,
        {
            task.id: task,
        },
    )

    assert context == {}
    
    