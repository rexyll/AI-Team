import pytest

from security.tool_permission import (
    EXECUTE,
    READ,
    WRITE,
    ToolPermissionError,
    ToolPermissionPolicy,
)


def test_policy_is_deny_by_default():
    policy = ToolPermissionPolicy()

    assert policy.allows("read_file", READ) is False
    assert policy.allows("write_file", WRITE) is False

    with pytest.raises(ToolPermissionError):
        policy.require("read_file", READ)


def test_policy_allows_explicit_capabilities_only():
    policy = ToolPermissionPolicy(
        {
            "read_file": {READ},
            "write_file": {WRITE},
            "run_command": {EXECUTE},
        }
    )

    assert policy.allows("read_file", READ)
    assert not policy.allows("read_file", WRITE)
    assert policy.allows("write_file", WRITE)
    assert policy.allows("run_command", EXECUTE)


def test_require_allows_explicit_capability():
    policy = ToolPermissionPolicy({"read_file": {READ}})

    policy.require("read_file", READ)


def test_require_rejects_undeclared_capability():
    policy = ToolPermissionPolicy({"read_file": {READ}})

    with pytest.raises(ToolPermissionError):
        policy.require("read_file", WRITE)


def test_unknown_capability_is_rejected():
    with pytest.raises(ValueError):
        ToolPermissionPolicy({"read_file": {"delete"}})

    policy = ToolPermissionPolicy({"read_file": {READ}})
    with pytest.raises(ValueError):
        policy.allows("read_file", "delete")


def test_invalid_tool_name_is_rejected():
    with pytest.raises(TypeError):
        ToolPermissionPolicy({"": {READ}})

    policy = ToolPermissionPolicy({"read_file": {READ}})
    with pytest.raises(TypeError):
        policy.allows("", READ)


def test_permission_policy_does_not_grant_path_escape():
    """Permission is independent from filesystem containment."""
    policy = ToolPermissionPolicy({"read_file": {READ}})

    assert policy.allows("read_file", READ)
    # WorkspaceSandbox remains the separate path-containment authority.
    # A read capability alone must never be interpreted as path authorization.
