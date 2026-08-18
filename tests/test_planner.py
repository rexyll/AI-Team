import pytest


from agents.planner import (
    _extract_json_object,
    _parse_plan_response,
    create_plan,
)


VALID_JSON = """
{
    "project": "demo",
    "summary": "demo project",
    "tasks": [
        {
            "id": "TASK-001",
            "title": "实现功能",
            "description": "实现核心功能",
            "role": "developer",
            "dependencies": []
        }
    ]
}
"""


def test_extract_plain_json():
    result = _extract_json_object(
        VALID_JSON
    )

    assert result.strip().startswith("{")
    assert result.strip().endswith("}")


def test_extract_markdown_json():
    response = f"""
    下面是项目计划：

    ```json
    {VALID_JSON}
    """
    
    result = _extract_json_object(response)

    assert result.strip().startswith("{")
    assert result.strip().endswith("}")
    
    
    
def test_extract_embedded_json():
    response = f"""
    Planner result:

    {VALID_JSON}

    以上是项目计划。
    """
    result = _extract_json_object(response)

    assert result.strip().startswith("{")
    assert result.strip().endswith("}")
    
def test_extract_rejects_empty_response():
    with pytest.raises(
    ValueError,
    match="空响应",
    ):
        _extract_json_object("")

def test_extract_rejects_response_without_json():
    with pytest.raises(
    ValueError,
    match="没有找到 JSON 对象",
    ):
        _extract_json_object(
    "这里没有任何 JSON"
    )

def test_extract_rejects_incomplete_json():
    with pytest.raises(
    ValueError,
    match="不完整的 JSON",
    ):
        _extract_json_object(
    '{"project": "demo"'
    )

def test_parse_valid_plan():
    plan = _parse_plan_response(
    VALID_JSON
    )

    assert plan["project"] == "demo"
    assert len(plan["tasks"]) == 1
    assert (
        plan["tasks"][0]["role"]
        == "developer"
    )

def test_parse_markdown_plan():
    response = f"""

    {VALID_JSON}

    """

    plan = _parse_plan_response(response)


    assert plan["project"] == "demo"

def test_parse_rejects_invalid_json():
    response = """
    {
        "project": "demo",
        "summary":
    }
    """

    with pytest.raises(
        ValueError,
        match="不是合法 JSON",
    ):
        _parse_plan_response(response)

def test_parse_rejects_non_object_root():
    response = """
    [
        {
        "id": "TASK-001"
        }
    ]
    """

    with pytest.raises(
        ValueError,
        match="根节点必须是对象",
    ):
        _parse_plan_response(response)

def test_parse_rejects_invalid_role():
    response = """
    {
        "project": "demo",
        "summary": "demo",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "test",
                "description": "test",
                "role": "unknown",
                "dependencies": []
            }
        ]
    }
    """

    with pytest.raises(
        ValueError,
        match="Invalid role",
    ):
        _parse_plan_response(response)

def test_parse_rejects_dependency_to_unknown_task():
    response = """
    {
        "project": "demo",
        "summary": "demo",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "test",
                "description": "test",
                "role": "developer",
                "dependencies": ["TASK-999"]
            }
        ]
    }
    """

    with pytest.raises(
        ValueError,
        match="unknown task",
    ):
        _parse_plan_response(response)

def test_parse_rejects_circular_dependencies():
    response = """
    {
        "project": "demo",
        "summary": "demo",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "A",
                "description": "A",
                "role": "developer",
                "dependencies": ["TASK-002"]
            },
            {
                "id": "TASK-002",
                "title": "B",
                "description": "B",
                "role": "tester",
                "dependencies": ["TASK-001"]
            }
        ]
    }
    """

    with pytest.raises(
        ValueError,
        match="Circular task dependency detected",
    ):
        _parse_plan_response(response)
    
def test_create_plan_recovers_from_invalid_json(monkeypatch):
    responses = iter(
        [
            "this is invalid json",
            """
            {
                "project": "测试项目",
                "summary": "测试摘要",
                "tasks": [
                    {
                        "id": "TASK-001",
                        "title": "开发",
                        "description": "实现功能",
                        "role": "developer",
                        "dependencies": []
                    }
                ]
            }
            """,
        ]
    )

    def fake_ask_ai(*args, **kwargs):
        return next(responses)

    monkeypatch.setattr(
        "agents.planner.ask_ai",
        fake_ask_ai,
    )

    result = create_plan("创建一个测试项目")

    assert result["project"] == "测试项目"
    assert result["summary"] == "测试摘要"
    assert result["tasks"][0]["id"] == "TASK-001"
    
def test_create_plan_stops_after_max_retries(monkeypatch):
    calls = []

    def fake_ask_ai(*args, **kwargs):
        calls.append(1)
        return "invalid json"

    monkeypatch.setattr(
        "agents.planner.ask_ai",
        fake_ask_ai,
    )

    with pytest.raises(
        ValueError,
        match="多次尝试后仍无法生成合法计划",
    ):
        create_plan("创建一个测试项目")

    assert len(calls) == 3
    
    
def test_create_plan_recovers_from_schema_error(monkeypatch):
    responses = iter(
        [
            """
            {
                "project": "测试项目",
                "summary": "测试摘要",
                "tasks": [
                    {
                        "id": "TASK-001",
                        "title": "开发",
                        "description": "实现功能",
                        "role": "invalid-role",
                        "dependencies": []
                    }
                ]
            }
            """,
            """
            {
                "project": "测试项目",
                "summary": "测试摘要",
                "tasks": [
                    {
                        "id": "TASK-001",
                        "title": "开发",
                        "description": "实现功能",
                        "role": "developer",
                        "dependencies": []
                    }
                ]
            }
            """,
        ]
    )

    def fake_ask_ai(*args, **kwargs):
        return next(responses)

    monkeypatch.setattr(
        "agents.planner.ask_ai",
        fake_ask_ai,
    )

    result = create_plan("创建一个测试项目")

    assert result["tasks"][0]["role"] == "developer"