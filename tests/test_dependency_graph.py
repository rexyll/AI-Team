import pytest

from runtime.dependency_graph import (
    build_dependency_graph,
    get_execution_layers,
    topological_sort,
)


def test_build_dependency_graph():
    tasks = [
        {
            "id": "TASK-001",
            "title": "设计",
            "description": "系统设计",
            "role": "architect",
            "dependencies": [],
        },
        {
            "id": "TASK-002",
            "title": "开发",
            "description": "功能开发",
            "role": "developer",
            "dependencies": ["TASK-001"],
        },
        {
            "id": "TASK-003",
            "title": "测试",
            "description": "功能测试",
            "role": "tester",
            "dependencies": ["TASK-002"],
        },
    ]

    graph = build_dependency_graph(tasks)

    assert graph == {
        "TASK-001": [],
        "TASK-002": ["TASK-001"],
        "TASK-003": ["TASK-002"],
    }


def test_topological_sort_returns_dependency_first_order():
    graph = {
        "TASK-001": [],
        "TASK-002": ["TASK-001"],
        "TASK-003": ["TASK-002"],
    }

    result = topological_sort(graph)

    assert result == [
        "TASK-001",
        "TASK-002",
        "TASK-003",
    ]


def test_topological_sort_supports_parallel_tasks():
    graph = {
        "TASK-001": [],
        "TASK-002": ["TASK-001"],
        "TASK-003": ["TASK-001"],
        "TASK-004": ["TASK-002", "TASK-003"],
    }

    result = topological_sort(graph)

    assert result.index("TASK-001") < result.index("TASK-002")
    assert result.index("TASK-001") < result.index("TASK-003")
    assert result.index("TASK-002") < result.index("TASK-004")
    assert result.index("TASK-003") < result.index("TASK-004")


def test_topological_sort_rejects_unknown_dependency():
    graph = {
        "TASK-001": [],
        "TASK-002": ["TASK-999"],
    }

    with pytest.raises(
        ValueError,
        match="unknown task",
    ):
        topological_sort(graph)


def test_topological_sort_rejects_cycle():
    graph = {
        "TASK-001": ["TASK-003"],
        "TASK-002": ["TASK-001"],
        "TASK-003": ["TASK-002"],
    }

    with pytest.raises(
        ValueError,
        match="Circular task dependency detected",
    ):
        topological_sort(graph)


def test_get_execution_layers_for_linear_dependencies():
    graph = {
        "TASK-001": [],
        "TASK-002": ["TASK-001"],
        "TASK-003": ["TASK-002"],
    }

    layers = get_execution_layers(graph)

    assert layers == [
        ["TASK-001"],
        ["TASK-002"],
        ["TASK-003"],
    ]


def test_get_execution_layers_for_parallel_dependencies():
    graph = {
        "TASK-001": [],
        "TASK-002": ["TASK-001"],
        "TASK-003": ["TASK-001"],
        "TASK-004": ["TASK-002", "TASK-003"],
    }

    layers = get_execution_layers(graph)

    assert layers == [
        ["TASK-001"],
        ["TASK-002", "TASK-003"],
        ["TASK-004"],
    ]


def test_get_execution_layers_supports_multiple_independent_tasks():
    graph = {
        "TASK-001": [],
        "TASK-002": [],
        "TASK-003": [],
    }

    layers = get_execution_layers(graph)

    assert layers == [
        [
            "TASK-001",
            "TASK-002",
            "TASK-003",
        ]
    ]


def test_get_execution_layers_rejects_cycle():
    graph = {
        "TASK-001": ["TASK-002"],
        "TASK-002": ["TASK-001"],
    }

    with pytest.raises(
        ValueError,
        match="Circular task dependency detected",
    ):
        get_execution_layers(graph)