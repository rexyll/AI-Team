import inspect
from typing import Any


class ToolArgumentValidationError(ValueError):
    """Raised when tool-call arguments violate a tool schema."""


def _matches_json_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
        )
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "null":
        return value is None
    return True


def _validate_schema_arguments(
    tool_name: str,
    arguments: Any,
    schema: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ToolArgumentValidationError(
            f"Invalid arguments for tool {tool_name!r}: "
            "arguments must be a JSON object"
        )

    parameters = schema.get("function", {}).get("parameters")
    if not isinstance(parameters, dict):
        raise ToolArgumentValidationError(
            f"Invalid schema for tool {tool_name!r}: parameters must be an object"
        )

    properties = parameters.get("properties", {})
    if not isinstance(properties, dict):
        raise ToolArgumentValidationError(
            f"Invalid schema for tool {tool_name!r}: properties must be an object"
        )

    required = parameters.get("required", [])
    if not isinstance(required, list):
        raise ToolArgumentValidationError(
            f"Invalid schema for tool {tool_name!r}: required must be a list"
        )

    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise ToolArgumentValidationError(
            f"Invalid arguments for tool {tool_name!r}: "
            f"unknown argument(s): {', '.join(unknown)}"
        )

    missing = [name for name in required if name not in arguments]
    if missing:
        raise ToolArgumentValidationError(
            f"Invalid arguments for tool {tool_name!r}: "
            f"missing required argument(s): {', '.join(missing)}"
        )

    for name, value in arguments.items():
        definition = properties.get(name)
        if not isinstance(definition, dict):
            raise ToolArgumentValidationError(
                f"Invalid schema for tool {tool_name!r}: "
                f"property {name!r} must be an object"
            )

        expected_type = definition.get("type")
        if isinstance(expected_type, str) and not _matches_json_type(
            value,
            expected_type,
        ):
            raise ToolArgumentValidationError(
                f"Invalid arguments for tool {tool_name!r}: "
                f"argument {name!r} must be of type {expected_type}"
            )

    return dict(arguments)


def validate_tool_arguments(
    tool_function,
    arguments: dict,
    schema: dict[str, Any] | None = None,
) -> tuple[dict, dict]:
    """Validate tool arguments against a schema when one is supplied.

    The legacy two-argument form keeps its filtering behavior for compatibility.
    The schema-aware form is strict: malformed, missing, unknown, or mistyped
    arguments raise ToolArgumentValidationError before tool execution.
    """
    if schema is not None:
        function = schema.get("function", {})
        tool_name = function.get("name")
        if not isinstance(tool_name, str) or not tool_name:
            raise ToolArgumentValidationError(
                "Invalid tool schema: function.name must be a non-empty string"
            )

        validated = _validate_schema_arguments(
            tool_name,
            arguments,
            schema,
        )
        return validated, {}

    if not isinstance(arguments, dict):
        raise TypeError("Tool arguments must be a dictionary")

    signature = inspect.signature(tool_function)
    allowed = set(signature.parameters.keys())

    valid_arguments = {
        key: value
        for key, value in arguments.items()
        if key in allowed
    }

    ignored_arguments = {
        key: value
        for key, value in arguments.items()
        if key not in allowed
    }

    return valid_arguments, ignored_arguments
