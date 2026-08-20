import pytest

from tools.registry import ToolRegistry


def _schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Test tool {name}",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }


def test_registry_register_get_and_list_contract():
    def first_tool() -> str:
        return "first"

    registry = ToolRegistry()
    registry.register("first", first_tool, _schema("first"))

    assert registry.get("first") is first_tool
    assert registry.list() == ["first"]
    assert registry.schemas() == [_schema("first")]


def test_registry_rejects_duplicate_tool_names():
    def first_tool() -> str:
        return "first"

    registry = ToolRegistry()
    registry.register("first", first_tool, _schema("first"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register("first", first_tool, _schema("first"))


def test_registry_rejects_unknown_tools():
    registry = ToolRegistry()

    with pytest.raises(KeyError, match="Unknown tool"):
        registry.get("missing")

    with pytest.raises(KeyError, match="Unknown tool"):
        registry.schema("missing")


def test_registry_rejects_invalid_registration():
    registry = ToolRegistry()

    with pytest.raises(TypeError, match="name"):
        registry.register(123, lambda: None, _schema("123"))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="non-empty"):
        registry.register("   ", lambda: None, _schema("   "))

    with pytest.raises(TypeError, match="callable"):
        registry.register("bad", object(), _schema("bad"))  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="schema"):
        registry.register("bad", lambda: None, None)  # type: ignore[arg-type]


def test_registry_requires_schema_name_to_match_registration_name():
    registry = ToolRegistry()

    with pytest.raises(ValueError, match="schema name"):
        registry.register("first", lambda: "first", _schema("other"))


def test_registry_returns_independent_schema_snapshots():
    registry = ToolRegistry()
    registry.register("first", lambda: "first", _schema("first"))

    schemas = registry.schemas()
    schemas[0]["function"]["description"] = "mutated"

    assert registry.schema("first")["function"]["description"] == "Test tool first"


def test_registry_schema_names_match_registered_tools():
    registry = ToolRegistry()
    registry.register("first", lambda: "first", _schema("first"))
    registry.register("second", lambda: "second", _schema("second"))

    assert {
        item["function"]["name"]
        for item in registry.schemas()
    } == set(registry.list())
