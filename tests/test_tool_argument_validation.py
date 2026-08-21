import pytest

from security.tool_guard import (
    ToolArgumentValidationError,
    validate_tool_arguments,
)
from tools.registry import TOOL_REGISTRY


def _schema(name: str) -> dict:
    return TOOL_REGISTRY.schema(name)


def test_validation_accepts_valid_arguments():
    arguments = {"path": "src"}

    valid, ignored = validate_tool_arguments(
        TOOL_REGISTRY.get("read_file"),
        arguments,
        schema=_schema("read_file"),
    )

    assert valid == arguments
    assert ignored == {}


def test_validation_rejects_malformed_arguments():
    with pytest.raises(ToolArgumentValidationError, match="JSON object"):
        validate_tool_arguments(
            TOOL_REGISTRY.get("read_file"),
            ["src"],  # type: ignore[arg-type]
            schema=_schema("read_file"),
        )


def test_validation_rejects_missing_required_arguments():
    with pytest.raises(
        ToolArgumentValidationError,
        match="missing required argument",
    ):
        validate_tool_arguments(
            TOOL_REGISTRY.get("write_file"),
            {"path": "demo.txt"},
            schema=_schema("write_file"),
        )


def test_validation_rejects_unknown_arguments():
    with pytest.raises(
        ToolArgumentValidationError,
        match="unknown argument",
    ):
        validate_tool_arguments(
            TOOL_REGISTRY.get("read_file"),
            {"path": "demo.txt", "unexpected": True},
            schema=_schema("read_file"),
        )


def test_validation_rejects_wrong_argument_types():
    with pytest.raises(
        ToolArgumentValidationError,
        match="must be of type string",
    ):
        validate_tool_arguments(
            TOOL_REGISTRY.get("read_file"),
            {"path": 123},  # type: ignore[dict-item]
            schema=_schema("read_file"),
        )


def test_validation_uses_schema_required_and_types_independently_of_python_signature():
    tool = TOOL_REGISTRY.get("run_command")
    schema = _schema("run_command")

    valid, ignored = validate_tool_arguments(
        tool,
        {"command": "pytest -q", "cwd": "."},
        schema=schema,
    )

    assert valid == {"command": "pytest -q", "cwd": "."}
    assert ignored == {}


def test_legacy_two_argument_validation_keeps_filtering_compatibility():
    def sample_tool(path: str, recursive: bool = False) -> tuple[str, bool]:
        return path, recursive

    valid, ignored = validate_tool_arguments(
        sample_tool,
        {
            "path": "src",
            "recursive": True,
            "unexpected": "ignored",
        },
    )

    assert valid == {"path": "src", "recursive": True}
    assert ignored == {"unexpected": "ignored"}
