from typing import Any

from config.tools_schema import TOOLS_SCHEMA
from tools.registry import ToolRegistry


CUSTOM_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "summarize_text",
        "description": "Return a deterministic short summary for example purposes.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to summarize.",
                }
            },
            "required": ["text"],
        },
    },
}


def summarize_text(*, text: str) -> dict[str, Any]:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return {"summary": text[:80]}


def build_example_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register("summarize_text", summarize_text, CUSTOM_TOOL_SCHEMA)
    return registry


if __name__ == "__main__":
    registry = build_example_registry()
    print("Built-in schemas:", len(TOOLS_SCHEMA))
    print("Custom tools:", registry.list())
    print(registry.get("summarize_text")(text="A deterministic tool example."))
