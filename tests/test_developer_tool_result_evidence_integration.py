from agents.developer import DeveloperAgent


def test_developer_tool_message_reduces_large_command_output() -> None:
    source = "setup output\n" + ("noise\n" * 2000) + "FAILED tests/test_example.py::test_case - assertion details"

    message = DeveloperAgent._build_tool_message("run_command", source)

    assert len(message) < len(source)
    assert message.endswith("FAILED tests/test_example.py::test_case - assertion details")
    assert "tool evidence truncated" in message


def test_developer_tool_message_keeps_large_file_head_and_tail() -> None:
    source = "from package import dependency\n" + ("body\n" * 2000) + "# important footer"

    message = DeveloperAgent._build_tool_message("read_file", source)

    assert len(message) < len(source)
    assert message.startswith("from package import dependency")
    assert message.endswith("# important footer")
    assert "tool evidence truncated" in message


def test_developer_tool_message_preserves_small_results() -> None:
    source = "3 passed in 0.42s"

    assert DeveloperAgent._build_tool_message("run_command", source) == source
