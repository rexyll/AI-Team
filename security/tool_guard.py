import inspect


def validate_tool_arguments(
    tool_function,
    arguments: dict,
) -> tuple[dict, dict]:

    signature = inspect.signature(
        tool_function
    )

    allowed = set(
        signature.parameters.keys()
    )

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

    return (
        valid_arguments,
        ignored_arguments,
    )