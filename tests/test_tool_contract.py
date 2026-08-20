import inspect

import pytest

from config.tools_schema import TOOLS_SCHEMA
from tools.filesystem import delete_file, list_files, move_file, read_file, write_file
from tools.git import git_command
from tools.registry import TOOLS
from tools.terminal import run_command


EXPECTED_TOOLS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "move_file": move_file,
    "delete_file": delete_file,
    "run_command": run_command,
    "git_command": git_command,
}


def _schema_by_name(name: str) -> dict:
    matches = [
        item["function"]
        for item in TOOLS_SCHEMA
        if item.get("function", {}).get("name") == name
    ]
    assert len(matches) == 1
    return matches[0]


def test_existing_tools_have_stable_registry_names():
    assert set(TOOLS) == set(EXPECTED_TOOLS)

    for name, implementation in EXPECTED_TOOLS.items():
        assert TOOLS[name] is implementation
        assert isinstance(name, str)
        assert name.strip()
        assert callable(implementation)


def test_tool_registry_functions_have_inspectable_execution_contracts():
    for name, tool in TOOLS.items():
        signature = inspect.signature(tool)
        assert signature.return_annotation is not inspect.Signature.empty, name

        schema = _schema_by_name(name)
        assert schema["name"] == name
        assert isinstance(schema.get("description"), str)
        assert schema["description"].strip()
        assert schema["parameters"]["type"] == "object"
        assert isinstance(schema["parameters"].get("properties"), dict)
        assert isinstance(schema["parameters"].get("required", []), list)


def test_tool_schema_names_and_registry_names_are_identical():
    schema_names = {
        item["function"]["name"]
        for item in TOOLS_SCHEMA
    }

    assert schema_names == set(TOOLS)


def test_tool_contract_does_not_embed_provider_specific_llm_configuration():
    for item in TOOLS_SCHEMA:
        function = item["function"]
        serialized = repr(function).lower()

        assert "openai" not in serialized
        assert "agnes" not in serialized
        assert "api_key" not in serialized
        assert "model" not in serialized
        assert "provider" not in serialized


def test_tool_schema_is_function_call_compatible():
    for item in TOOLS_SCHEMA:
        assert item["type"] == "function"
        function = item["function"]
        assert set(function) == {"name", "description", "parameters"}
        assert function["parameters"]["type"] == "object"

        required = function["parameters"].get("required", [])
        properties = function["parameters"]["properties"]
        assert set(required).issubset(properties)


def test_registry_tool_functions_are_not_bound_to_workflow_objects():
    for tool in TOOLS.values():
        assert inspect.isfunction(tool) or inspect.isbuiltin(tool)
        assert not inspect.ismethod(tool)


def test_existing_tool_contract_does_not_swallow_validation_boundary():
    with pytest.raises(TypeError):
        list_files(None)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        read_file(None)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        write_file(None, "content")  # type: ignore[arg-type]
