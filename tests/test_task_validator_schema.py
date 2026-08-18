import pytest

from runtime.task_validator import validate_plan


def valid_task(
    task_id="TASK-001",
    role="developer",
    dependencies=None,
):
    return {
        "id": task_id,
        "title": "测试任务",
        "description": "测试任务描述",
        "role": role,
        "dependencies": (
            []
            if dependencies is None
            else dependencies
        ),
    }


def valid_plan(tasks=None):
    return {
        "project": "test-project",
        "summary": "测试项目",
        "tasks": (
            [valid_task()]
            if tasks is None
            else tasks
        ),
    }


def test_valid_plan_passes():
    validate_plan(valid_plan())


def test_plan_requires_summary():
    plan = valid_plan()
    del plan["summary"]

    with pytest.raises(
        ValueError,
        match="Plan missing required fields",
    ):
        validate_plan(plan)


def test_plan_rejects_unknown_field():
    plan = valid_plan()
    plan["unexpected"] = "value"

    with pytest.raises(
        ValueError,
        match="Plan contains unknown fields",
    ):
        validate_plan(plan)


def test_task_requires_all_schema_fields():
    for field in (
        "id",
        "title",
        "description",
        "role",
        "dependencies",
    ):
        plan = valid_plan()
        del plan["tasks"][0][field]

        with pytest.raises(
            ValueError,
            match="missing required fields",
        ):
            validate_plan(plan)


def test_task_rejects_unknown_field():
    plan = valid_plan()
    plan["tasks"][0]["priority"] = "high"

    with pytest.raises(
        ValueError,
        match="contains unknown fields",
    ):
        validate_plan(plan)


def test_task_id_must_be_string():
    plan = valid_plan()
    plan["tasks"][0]["id"] = 123

    with pytest.raises(
        ValueError,
        match="id must be a string",
    ):
        validate_plan(plan)


def test_task_title_must_be_string():
    plan = valid_plan()
    plan["tasks"][0]["title"] = 123

    with pytest.raises(
        ValueError,
        match="title must be a string",
    ):
        validate_plan(plan)


def test_task_description_must_be_string():
    plan = valid_plan()
    plan["tasks"][0]["description"] = 123

    with pytest.raises(
        ValueError,
        match="description must be a string",
    ):
        validate_plan(plan)


def test_task_role_must_be_string():
    plan = valid_plan()
    plan["tasks"][0]["role"] = 123

    with pytest.raises(
        ValueError,
        match="role must be a string",
    ):
        validate_plan(plan)


def test_dependencies_must_contain_strings():
    plan = valid_plan(
        [
            valid_task(
                dependencies=[123],
            )
        ]
    )

    with pytest.raises(
        ValueError,
        match="Dependency of TASK-001 must be a string",
    ):
        validate_plan(plan)


def test_empty_dependency_id_is_rejected():
    plan = valid_plan(
        [
            valid_task(
                dependencies=[""],
            )
        ]
    )

    with pytest.raises(
        ValueError,
        match="Dependency of TASK-001 cannot be empty",
    ):
        validate_plan(plan)


def test_empty_project_is_rejected():
    plan = valid_plan()
    plan["project"] = "   "

    with pytest.raises(
        ValueError,
        match="Plan project cannot be empty",
    ):
        validate_plan(plan)


def test_empty_summary_is_rejected():
    plan = valid_plan()
    plan["summary"] = ""

    with pytest.raises(
        ValueError,
        match="Plan summary cannot be empty",
    ):
        validate_plan(plan)
        
def test_duplicate_dependency_is_rejected():
    plan = {
        "project": "test",
        "summary": "test",
        "tasks": [
            {
                "id": "TASK-001",
                "title": "任务一",
                "description": "任务一",
                "role": "developer",
                "dependencies": [],
            },
            {
                "id": "TASK-002",
                "title": "任务二",
                "description": "任务二",
                "role": "developer",
                "dependencies": [
                    "TASK-001",
                    "TASK-001",
                ],
            },
        ],
    }

    with pytest.raises(
        ValueError,
        match="duplicate dependency",
    ):
        validate_plan(plan)