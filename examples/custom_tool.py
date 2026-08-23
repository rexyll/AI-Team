import sys
from pathlib import Path
from typing import Any

# Bootstrap repository-root imports so the file runs standalone
# (``python examples/custom_tool.py``) as well as via pytest.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config.tools_schema import TOOLS_SCHEMA  # noqa: E402
from tools.registry import ToolRegistry  # noqa: E402


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
