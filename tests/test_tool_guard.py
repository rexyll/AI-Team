from security.tool_guard import validate_tool_arguments


def sample_tool(path, recursive=False):
    return path, recursive


def test_tool_argument_filtering():

    arguments = {
        "path": "accounting_db",
        "recursive": True,
        "unexpected": "hello",
    }

    valid, ignored = validate_tool_arguments(
        sample_tool,
        arguments,
    )

    assert valid == {
        "path": "accounting_db",
        "recursive": True,
    }

    assert ignored == {
        "unexpected": "hello",
    }