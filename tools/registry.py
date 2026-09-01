from copy import deepcopy
from typing import Any, Callable

from config.tools_schema import TOOLS_SCHEMA
from tools.filesystem import (
    list_files,
    read_file,
    write_file,
    move_file,
    delete_file,
)
from tools.terminal import run_command


ToolFunction = Callable[..., Any]


class ToolRegistry:
    """Provider-independent registry for executable tools and their schemas."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolFunction] = {}
        self._schemas: dict[str, dict[str, Any]] = {}

    def register(
        self,
        name: str,
        implementation: ToolFunction,
        schema: dict[str, Any],
    ) -> None:
        """Register one tool and its function-call schema."""
        if not isinstance(name, str):
            raise TypeError("Tool name must be a string")
        if not name.strip():
            raise ValueError("Tool name must be non-empty")
        if not callable(implementation):
            raise TypeError("Tool implementation must be callable")
        if not isinstance(schema, dict):
            raise TypeError("Tool schema must be a dictionary")

        if name in self._tools:
            raise ValueError(f"Tool {name!r} is already registered")

        function = schema.get("function")
        if not isinstance(function, dict):
            raise ValueError("Tool schema must contain a function object")
        schema_name = function.get("name")
        if schema_name != name:
            raise ValueError(
                "Tool schema name must match registration name: "
                f"{schema_name!r} != {name!r}"
            )

        self._tools[name] = implementation
        self._schemas[name] = deepcopy(schema)

    def get(self, name: str) -> ToolFunction:
        """Return a registered tool implementation."""
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name]

    def schema(self, name: str) -> dict[str, Any]:
        """Return an independent schema snapshot for one registered tool."""
        if name not in self._schemas:
            raise KeyError(f"Unknown tool: {name}")
        return deepcopy(self._schemas[name])

    def list(self) -> list[str]:
        """Return registered tool names in registration order."""
        return list(self._tools)

    def schemas(self):
        """Return independent function-call schemas in registration order."""
        return [self.schema(name) for name in self._tools]


_DEFAULT_IMPLEMENTATIONS: dict[str, ToolFunction] = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "move_file": move_file,
    "delete_file": delete_file,
    "run_command": run_command,
}


TOOL_REGISTRY = ToolRegistry()

for _schema in TOOLS_SCHEMA:
    _function = _schema.get("function", {})
    _name = _function.get("name")
    if _name not in _DEFAULT_IMPLEMENTATIONS:
        raise ValueError(
            f"Tool schema has no registered implementation: {_name!r}"
        )
    TOOL_REGISTRY.register(
        _name,
        _DEFAULT_IMPLEMENTATIONS[_name],
        _schema,
    )


# Legacy compatibility: existing callers can continue to use TOOLS[name].
TOOLS = {
    name: TOOL_REGISTRY.get(name)
    for name in TOOL_REGISTRY.list()
}
