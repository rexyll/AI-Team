from pathlib import Path
import shutil
import subprocess

import pytest

from runtime.host_git import GitOperationRequest, HostGitOperationService
from security.runtime_capability import HOST_ONLY_TOOLS, RuntimeCapabilityPolicy
from security.tool_permission import ToolPermissionError
from security.workspace import WorkspaceSandbox
from tools.registry import TOOL_REGISTRY


def _service(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(workspace)],
        check=True,
        capture_output=True,
        text=True,
    )
    calls = []

    def fake_git(
        command: str,
        cwd: str,
        *,
        sandbox=None,
        env=None,
    ) -> str:
        calls.append((command, cwd, sandbox))
        if command == "rev-parse --show-toplevel":
            return f"exit_code=0\n{workspace}\n"
        return "exit_code=0\nok\n"

    monkeypatch.setattr("runtime.host_git.git_tool.git_command", fake_git)
    return HostGitOperationService(WorkspaceSandbox(tmp_path)), workspace, calls


def test_host_service_exposes_only_semantic_git_operations():
    assert "command" not in GitOperationRequest.__dataclass_fields__
    for method in (
        "status", "diff", "log", "show", "branch", "rev_parse", "add", "commit",
        "init", "tag", "is_repository", "head_commit",
    ):
        assert callable(getattr(HostGitOperationService, method))


def test_agent_registry_does_not_expose_raw_git_command():
    assert "git_command" not in TOOL_REGISTRY.list()


def test_raw_git_is_host_only_for_every_agent_role():
    policy = RuntimeCapabilityPolicy()
    assert HOST_ONLY_TOOLS == {"git_command"}
    for role in ("architect", "developer", "tester", "reviewer", "planner"):
        assert not policy.allows(role, "git_command")
        with pytest.raises(ToolPermissionError, match="host-only"):
            policy.require(role, "git_command")
        assert "git_command" not in policy.filter_tool_names(role, ["git_command"])


def test_status_is_host_owned_and_validates_repository(tmp_path, monkeypatch):
    service, workspace, calls = _service(tmp_path, monkeypatch)
    assert service.status(str(workspace)) == "exit_code=0\nok\n"
    assert [(command, cwd) for command, cwd, _ in calls] == [
        ("rev-parse --show-toplevel", str(workspace)),
        ("status --short", str(workspace)),
    ]
    assert all(sandbox is not None for _, _, sandbox in calls)


def test_add_anchors_relative_paths_to_repository_workspace(tmp_path, monkeypatch):
    service, workspace, calls = _service(tmp_path, monkeypatch)
    target = workspace / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("pass", encoding="utf-8")

    service.add(str(workspace), ["src/app.py"])

    expected = str(Path("src") / "app.py")
    assert calls[-1][0:2] == (f'add "{expected}"', str(workspace))


def test_add_rejects_workspace_escape(tmp_path, monkeypatch):
    service, workspace, _ = _service(tmp_path, monkeypatch)
    with pytest.raises(PermissionError):
        service.add(str(workspace), ["../outside.txt"])


def test_commit_rejects_empty_and_multiline_messages(tmp_path, monkeypatch):
    service, workspace, _ = _service(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="non-empty"):
        service.commit(str(workspace), "   ")
    with pytest.raises(ValueError, match="single-line"):
        service.commit(str(workspace), "first\nsecond")


def test_revision_rejects_option_injection(tmp_path, monkeypatch):
    service, workspace, _ = _service(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="must not start"):
        service.show(str(workspace), revision="--output=/tmp/x")


def test_init_bypasses_repository_requirement(tmp_path, monkeypatch):
    service, workspace, calls = _service(tmp_path, monkeypatch)
    shutil.rmtree(workspace / ".git")

    service.init(str(workspace))

    assert calls[-1][0:2] == ("init", str(workspace))


def test_is_repository_reflects_rev_parse_outcome(tmp_path, monkeypatch):
    service, workspace, _ = _service(tmp_path, monkeypatch)
    assert service.is_repository(str(workspace)) is True

    def failing_git(command: str, cwd: str, *, sandbox=None) -> str:
        if command == "rev-parse --show-toplevel":
            return "exit_code=128\nfatal: not a git repository\n"
        return "exit_code=0\nok\n"

    monkeypatch.setattr("runtime.host_git.git_tool.git_command", failing_git)
    assert service.is_repository(str(workspace)) is False


def test_tag_annotated_and_lightweight_forms(tmp_path, monkeypatch):
    service, workspace, calls = _service(tmp_path, monkeypatch)

    service.tag(str(workspace), "v1.0.0", message="release 1.0.0")
    service.tag(str(workspace), "v0.9.0")

    tag_commands = [command for command, _, _ in calls if command.startswith("tag")]
    assert tag_commands == ['tag -a "v1.0.0" -m "release 1.0.0"', 'tag "v0.9.0"']


def test_tag_rejects_unsafe_names(tmp_path, monkeypatch):
    service, workspace, _ = _service(tmp_path, monkeypatch)
    for bad in ("-x", "v 1", "v~1", "v^1", "v:1", "v?1", "v*1", "v..1", "v1.", ""):
        with pytest.raises(ValueError):
            service.tag(str(workspace), bad)


def test_head_commit_parses_sha(tmp_path, monkeypatch):
    service, workspace, _ = _service(tmp_path, monkeypatch)

    def sha_git(command: str, cwd: str, *, sandbox=None) -> str:
        if command == "rev-parse --show-toplevel":
            return f"exit_code=0\n{workspace}\n"
        if command == "rev-parse HEAD":
            return "exit_code=0\nabc123def4567890abc123def4567890abc12345\n"
        return "exit_code=0\nok\n"

    monkeypatch.setattr("runtime.host_git.git_tool.git_command", sha_git)
    assert service.head_commit(str(workspace)) == "abc123def4567890abc123def4567890abc12345"


def test_host_remote_url_uses_fixed_host_owned_git_argument_vector(tmp_path, monkeypatch):
    from types import SimpleNamespace

    service, workspace, _ = _service(tmp_path, monkeypatch)
    calls = []

    def fake_run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout="https://github.com/acme/widget.git\n",
            stderr="",
        )

    monkeypatch.setattr("runtime.host_git.subprocess.run", fake_run)

    assert service.remote_url(str(workspace)) == "https://github.com/acme/widget.git"
    assert calls[0][0] == ["git", "remote", "get-url", "--push", "--all", "origin"]
    assert calls[0][1]["shell"] is False


def test_host_remote_url_rejects_multiple_effective_push_destinations(tmp_path, monkeypatch):
    from types import SimpleNamespace

    service, workspace, _ = _service(tmp_path, monkeypatch)

    def fake_run(arguments, **kwargs):
        assert arguments == ["git", "remote", "get-url", "--push", "--all", "origin"]
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "https://github.com/acme/widget.git\n"
                "https://github.com/attacker/widget.git\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("runtime.host_git.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="exactly one push destination"):
        service.remote_url(str(workspace))


def test_host_push_uses_non_force_refspec_and_rejects_unsafe_branch(tmp_path, monkeypatch):
    from types import SimpleNamespace

    service, workspace, _ = _service(tmp_path, monkeypatch)
    calls = []
    call_kwargs = []

    def fake_run(arguments, **kwargs):
        calls.append(arguments)
        call_kwargs.append(kwargs)
        if arguments[1] == "config":
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if arguments[1:5] == ["remote", "get-url", "--push", "--all"]:
            return SimpleNamespace(
                returncode=0,
                stdout="https://github.com/acme/widget.git\n",
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="pushed\n", stderr="")

    monkeypatch.setattr("runtime.host_git.subprocess.run", fake_run)

    result = service.push(
        str(workspace),
        branch="release/1.2",
        commit_sha="a" * 40,
        expected_remote_url="https://github.com/acme/widget.git",
    )

    assert result == "exit_code=0\npushed\n"
    assert calls == [
        ["git", "config", "--local", "--get-regexp", r"^credential(\..*)?\.helper$"],
        ["git", "config", "--local", "--get-regexp", r"^include(if)?\..*"],
        ["git", "config", "--local", "--get-regexp", r"^http\..*"],
        ["git", "config", "--worktree", "--get-regexp", r"^credential(\..*)?\.helper$"],
        ["git", "config", "--worktree", "--get-regexp", r"^include(if)?\..*"],
        ["git", "config", "--worktree", "--get-regexp", r"^http\..*"],
        [
            "git", "config", "--get-regexp",
            r"^url\..*\.(insteadOf|pushInsteadOf)$",
        ],
        ["git", "remote", "get-url", "--push", "--all", "origin"],
        [
            "git",
            "push",
            "--porcelain",
            "--no-verify",
            "--no-follow-tags",
            "--no-recurse-submodules",
            "--receive-pack=git-receive-pack",
            "https://github.com/acme/widget.git",
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:refs/heads/release/1.2",
        ],
    ]
    assert call_kwargs[-1]["env"]["GIT_SSH_COMMAND"] == "ssh -o BatchMode=yes"
    assert call_kwargs[-1]["env"]["GIT_SSH_VARIANT"] == "ssh"
    for branch in ("--force", "release/../main", "bad branch", "release//main", "release/"):
        with pytest.raises(ValueError, match="branch name"):
            service.push(
                str(workspace),
                branch=branch,
                commit_sha="a" * 40,
                expected_remote_url="https://github.com/acme/widget.git",
            )


def test_host_push_rejects_destination_drift_before_transport(tmp_path, monkeypatch):
    from types import SimpleNamespace

    service, workspace, _ = _service(tmp_path, monkeypatch)
    calls = []

    def fake_run(arguments, **kwargs):
        calls.append(arguments)
        if arguments[1] == "config":
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout="https://github.com/acme/attacker.git\n",
            stderr="",
        )

    monkeypatch.setattr("runtime.host_git.subprocess.run", fake_run)

    with pytest.raises(PermissionError, match="destination changed after approval"):
        service.push(
            str(workspace),
            branch="release/1.2",
            commit_sha="a" * 40,
            expected_remote_url="https://github.com/acme/widget.git",
        )

    assert calls == [
        ["git", "config", "--local", "--get-regexp", r"^credential(\..*)?\.helper$"],
        ["git", "config", "--local", "--get-regexp", r"^include(if)?\..*"],
        ["git", "config", "--local", "--get-regexp", r"^http\..*"],
        ["git", "config", "--worktree", "--get-regexp", r"^credential(\..*)?\.helper$"],
        ["git", "config", "--worktree", "--get-regexp", r"^include(if)?\..*"],
        ["git", "config", "--worktree", "--get-regexp", r"^http\..*"],
        ["git", "config", "--get-regexp", r"^url\..*\.(insteadOf|pushInsteadOf)$"],
        ["git", "remote", "get-url", "--push", "--all", "origin"],
    ]


def test_host_push_rejects_repository_scoped_credential_helpers(tmp_path, monkeypatch):
    from types import SimpleNamespace

    service, workspace, _ = _service(tmp_path, monkeypatch)
    calls = []

    def fake_run(arguments, **kwargs):
        calls.append(arguments)
        return SimpleNamespace(
            returncode=0,
            stdout="credential.https://github.com.helper !sh -c 'touch /tmp/owned'\n",
            stderr="",
        )

    monkeypatch.setattr("runtime.host_git.subprocess.run", fake_run)

    with pytest.raises(PermissionError, match="credential helpers"):
        service.push(
            str(workspace),
            branch="release/1.2",
            commit_sha="a" * 40,
            expected_remote_url="https://github.com/acme/widget.git",
        )

    assert calls == [[
        "git", "config", "--local", "--get-regexp", r"^credential(\..*)?\.helper$"
    ]]


def test_host_push_rejects_worktree_credential_helpers(tmp_path, monkeypatch):
    from types import SimpleNamespace

    service, workspace, _ = _service(tmp_path, monkeypatch)
    calls = []

    def fake_run(arguments, **kwargs):
        calls.append(arguments)
        if arguments[1:4] == ["config", "--local", "--get-regexp"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if arguments[1:4] == ["config", "--worktree", "--get-regexp"] and "credential" in arguments[-1]:
            return SimpleNamespace(returncode=0, stdout="credential.helper manager\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr("runtime.host_git.subprocess.run", fake_run)

    with pytest.raises(PermissionError, match="credential helpers"):
        service.push(
            str(workspace),
            branch="release/1.2",
            commit_sha="a" * 40,
            expected_remote_url="https://github.com/acme/widget.git",
        )

    assert len(calls) == 4
    assert calls[-1] == [
        "git", "config", "--worktree", "--get-regexp", r"^credential(\..*)?\.helper$"
    ]


def test_host_push_rejects_repository_local_config_includes(tmp_path, monkeypatch):
    from types import SimpleNamespace

    service, workspace, _ = _service(tmp_path, monkeypatch)
    calls = []

    def fake_run(arguments, **kwargs):
        calls.append(arguments)
        if arguments[1:4] == ["config", "--local", "--get-regexp"] and "credential" in arguments[-1]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if arguments[1:4] == ["config", "--local", "--get-regexp"]:
            return SimpleNamespace(
                returncode=0,
                stdout="includeif.gitdir:/tmp/workspace.path /tmp/untrusted.inc\n",
                stderr="",
            )
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr("runtime.host_git.subprocess.run", fake_run)

    with pytest.raises(PermissionError, match="config includes"):
        service.push(
            str(workspace),
            branch="release/1.2",
            commit_sha="a" * 40,
            expected_remote_url="https://github.com/acme/widget.git",
        )

    assert len(calls) == 2
    assert calls[-1] == [
        "git", "config", "--local", "--get-regexp", r"^include(if)?\..*"
    ]


def test_host_push_rejects_git_url_rewrite_rules_from_all_config_scopes(tmp_path, monkeypatch):
    from types import SimpleNamespace

    service, workspace, _ = _service(tmp_path, monkeypatch)
    calls = []

    def fake_run(arguments, **kwargs):
        calls.append(arguments)
        if arguments[1:] == [
            "config", "--get-regexp", r"^url\..*\.(insteadOf|pushInsteadOf)$"
        ]:
            return SimpleNamespace(
                returncode=0,
                stdout="url.ssh://attacker.example/.insteadof https://github.com/\n",
                stderr="",
            )
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr("runtime.host_git.subprocess.run", fake_run)

    with pytest.raises(PermissionError, match="URL rewrite rules"):
        service.push(
            str(workspace),
            branch="release/1.2",
            commit_sha="a" * 40,
            expected_remote_url="https://github.com/acme/widget.git",
        )

    assert calls == [
        ["git", "config", "--local", "--get-regexp", r"^credential(\..*)?\.helper$"],
        ["git", "config", "--local", "--get-regexp", r"^include(if)?\..*"],
        ["git", "config", "--local", "--get-regexp", r"^http\..*"],
        ["git", "config", "--worktree", "--get-regexp", r"^credential(\..*)?\.helper$"],
        ["git", "config", "--worktree", "--get-regexp", r"^include(if)?\..*"],
        ["git", "config", "--worktree", "--get-regexp", r"^http\..*"],
        ["git", "config", "--get-regexp", r"^url\..*\.(insteadOf|pushInsteadOf)$"],
    ]


def test_host_push_rejects_environment_injected_url_rewrite_rules(tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace

    service, workspace, _ = _service(tmp_path, monkeypatch)
    calls = []
    real_run = subprocess.run

    def recording_run(arguments, **kwargs):
        calls.append(arguments)
        return real_run(arguments, **kwargs)

    monkeypatch.setattr("runtime.host_git.subprocess.run", recording_run)
    env = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "url.https://attacker.example/.insteadOf",
        "GIT_CONFIG_VALUE_0": "https://github.com/",
    }

    with pytest.raises(PermissionError, match="Git URL rewrite rules"):
        service.push(
            str(workspace),
            branch="release/1.2",
            commit_sha="a" * 40,
            expected_remote_url="https://github.com/acme/widget.git",
            env=env,
        )

    assert calls == [
        ["git", "config", "--local", "--get-regexp", r"^credential(\..*)?\.helper$"],
        ["git", "config", "--local", "--get-regexp", r"^include(if)?\..*"],
        ["git", "config", "--local", "--get-regexp", r"^http\..*"],
        ["git", "config", "--worktree", "--get-regexp", r"^credential(\..*)?\.helper$"],
        ["git", "config", "--worktree", "--get-regexp", r"^include(if)?\..*"],
        ["git", "config", "--worktree", "--get-regexp", r"^http\..*"],
        ["git", "config", "--get-regexp", r"^url\..*\.(insteadOf|pushInsteadOf)$"],
    ]


@pytest.mark.parametrize(
    "variable",
    [
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_NAMESPACE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_SHALLOW_FILE",
        "GIT_CEILING_DIRECTORIES",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM",
        "GIT_REPLACE_REF_BASE",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_EXEC_PATH",
        "GIT_PREFIX",
        "GIT_ASKPASS",
        "GIT_ASKPASS_REQUIRE",
        "SSH_ASKPASS",
        "SSH_ASKPASS_REQUIRE",
        "GIT_PROXY_COMMAND",
        "GIT_SSH",
        "GIT_SSH_COMMAND",
        "GIT_SSH_VARIANT",
        "GIT_CURL_VERBOSE",
        "GIT_TRACE",
        "GIT_TRACE_CURL",
        "GIT_TRACE_CURL_NO_DATA",
        "GIT_TRACE_PACKET",
        "GIT_TRACE2",
        "GIT_TRACE2_EVENT",
        "GIT_TRACE2_PERF",
        "GIT_TRACE2_CONFIG_PARAMS",
        "git_dir",
        "git_trace_curl",
    ],
)
def test_host_push_rejects_git_process_environment_overrides(
    tmp_path, monkeypatch, variable
):
    service, workspace, git_calls = _service(tmp_path, monkeypatch)

    with pytest.raises(PermissionError, match="Git process environment overrides"):
        service.push(
            str(workspace),
            branch="release/1.2",
            commit_sha="a" * 40,
            expected_remote_url="https://github.com/acme/widget.git",
            env={variable: "untrusted-context-override"},
        )

    # The guard runs before rev-parse or any other Git subprocess.
    assert git_calls == []


def test_host_push_rejects_environment_injected_credential_helpers(tmp_path, monkeypatch):
    from types import SimpleNamespace

    service, workspace, _ = _service(tmp_path, monkeypatch)
    calls = []

    def fake_run(arguments, **kwargs):
        calls.append(arguments)
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr("runtime.host_git.subprocess.run", fake_run)
    env = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "credential.helper",
        "GIT_CONFIG_VALUE_0": "!sh -c 'touch /tmp/owned'",
    }

    with pytest.raises(PermissionError, match="Git command/environment config overrides"):
        service.push(
            str(workspace),
            branch="release/1.2",
            commit_sha="a" * 40,
            expected_remote_url="https://github.com/acme/widget.git",
            env=env,
        )

    assert calls == [
        ["git", "config", "--local", "--get-regexp", r"^credential(\..*)?\.helper$"],
        ["git", "config", "--local", "--get-regexp", r"^include(if)?\..*"],
        ["git", "config", "--local", "--get-regexp", r"^http\..*"],
        ["git", "config", "--worktree", "--get-regexp", r"^credential(\..*)?\.helper$"],
        ["git", "config", "--worktree", "--get-regexp", r"^include(if)?\..*"],
        ["git", "config", "--worktree", "--get-regexp", r"^http\..*"],
        ["git", "config", "--get-regexp", r"^url\..*\.(insteadOf|pushInsteadOf)$"],
    ]


@pytest.mark.parametrize(
    "variable",
    [
        "GIT_CONFIG",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_KEY_0",
        "GIT_CONFIG_VALUE_0",
        "git_config_global",
    ],
)
def test_host_push_rejects_all_git_config_environment_overrides(tmp_path, monkeypatch, variable):
    from types import SimpleNamespace

    service, workspace, _ = _service(tmp_path, monkeypatch)
    calls = []

    def fake_run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr("runtime.host_git.subprocess.run", fake_run)
    env = {variable: "untrusted-config-override"}

    with pytest.raises(PermissionError, match="Git command/environment config overrides"):
        service.push(
            str(workspace),
            branch="release/1.2",
            commit_sha="a" * 40,
            expected_remote_url="https://github.com/acme/widget.git",
            env=env,
        )

    assert len(calls) == 7
    assert all(
        not any(key.upper() == "GIT_CONFIG" or key.upper().startswith("GIT_CONFIG_") for key in call_env["env"])
        for _, call_env in calls[:6]
    )
    assert [arguments for arguments, _ in calls] == [
        ["git", "config", "--local", "--get-regexp", r"^credential(\..*)?\.helper$"],
        ["git", "config", "--local", "--get-regexp", r"^include(if)?\..*"],
        ["git", "config", "--local", "--get-regexp", r"^http\..*"],
        ["git", "config", "--worktree", "--get-regexp", r"^credential(\..*)?\.helper$"],
        ["git", "config", "--worktree", "--get-regexp", r"^include(if)?\..*"],
        ["git", "config", "--worktree", "--get-regexp", r"^http\..*"],
        ["git", "config", "--get-regexp", r"^url\..*\.(insteadOf|pushInsteadOf)$"],
    ]


@pytest.mark.parametrize(
    ("config_kind", "expected_error"),
    [
        ("local-helper", "credential helpers"),
        ("url-helper", "credential helpers"),
        ("local-include-if", "config includes"),
        ("worktree-helper", "credential helpers"),
        ("local-http-ssl-verify", "HTTP transport overrides"),
        ("local-http-extra-header", "HTTP transport overrides"),
        ("worktree-http-ssl-verify", "HTTP transport overrides"),
    ],
)
def test_host_push_rejects_real_repository_scoped_git_config(
    tmp_path, config_kind, expected_error
):
    if shutil.which("git") is None:
        pytest.skip("Git executable is unavailable")

    workspace = tmp_path / "repo"
    workspace.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(workspace)],
        check=True,
        capture_output=True,
        text=True,
    )
    marker = tmp_path / "credential-helper-executed"
    helper = f"!touch {marker}"

    if config_kind == "local-helper":
        subprocess.run(
            ["git", "config", "--local", "--add", "credential.helper", helper],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
    elif config_kind == "url-helper":
        subprocess.run(
            [
                "git", "config", "--local", "--add",
                "credential.https://github.com.helper", helper,
            ],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
    elif config_kind == "local-include-if":
        included = tmp_path / "untrusted.inc"
        included.write_text(f"[credential]\n\thelper = {helper}\n", encoding="utf-8")
        subprocess.run(
            [
                "git", "config", "--local", "--add",
                f"includeIf.gitdir:{workspace / '.git'}.path", str(included),
            ],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
    elif config_kind == "local-http-ssl-verify":
        subprocess.run(
            ["git", "config", "--local", "http.sslVerify", "false"],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
    elif config_kind == "local-http-extra-header":
        subprocess.run(
            [
                "git", "config", "--local", "--add",
                "http.extraHeader", "Authorization: Bearer repo-controlled",
            ],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
    elif config_kind == "worktree-http-ssl-verify":
        subprocess.run(
            ["git", "config", "extensions.worktreeConfig", "true"],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "config", "--worktree", "http.sslVerify", "false"],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
    elif config_kind == "worktree-helper":
        subprocess.run(
            ["git", "config", "extensions.worktreeConfig", "true"],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "config", "--worktree", "--add", "credential.helper", helper],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        raise AssertionError(f"unknown fixture: {config_kind}")

    service = HostGitOperationService(WorkspaceSandbox(tmp_path))
    with pytest.raises(PermissionError, match=expected_error):
        service.push(
            str(workspace),
            branch="release/1.2",
            commit_sha="a" * 40,
            expected_remote_url="https://github.com/acme/widget.git",
        )
    assert not marker.exists()


def test_agent_git_parser_still_rejects_host_only_remote_and_push():
    from tools.git import _parse_git_command

    for command in ("push origin HEAD:refs/heads/main", "remote get-url origin"):
        with pytest.raises(PermissionError, match="not allowed"):
            _parse_git_command(command)



def test_host_push_publishes_only_the_approved_sha_to_a_real_bare_repository(tmp_path):
    """Exercise HostGitOperationService against real local Git transport.

    This verifies the subprocess/argv boundary and exact ref update without
    pretending to exercise GitHub authentication, PR APIs, CI or reviews.
    """
    import os
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("Git executable is unavailable")

    remote = tmp_path / "sandbox.git"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def git(*arguments, cwd=None):
        return subprocess.run(
            ["git", *arguments],
            cwd=str(cwd) if cwd is not None else None,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()

    git("init", "--bare", "--quiet", str(remote))
    git("init", "--quiet", str(workspace))
    git("config", "user.name", "Host Git Integration", cwd=workspace)
    git("config", "user.email", "host-git@example.invalid", cwd=workspace)
    (workspace / "payload.txt").write_text("approved host push\n", encoding="utf-8")
    git("add", "payload.txt", cwd=workspace)
    git("commit", "--quiet", "-m", "approved fixture", cwd=workspace)

    approved_sha = git("rev-parse", "HEAD", cwd=workspace)
    target_branch = "feature/host-transport-integration"
    git("remote", "add", "origin", str(remote), cwd=workspace)
    git("config", "remote.origin.mirror", "true", cwd=workspace)
    git("config", "push.followTags", "true", cwd=workspace)
    git("tag", "-a", "fixture-tag", "-m", "must not be auto-pushed", cwd=workspace)

    hook_marker = tmp_path / "pre-push-hook-ran"
    hook = workspace / ".git" / "hooks" / "pre-push"
    hook.write_text(f"#!/bin/sh\nprintf 'called' > '{hook_marker}'\n", encoding="utf-8")
    os.chmod(hook, 0o700)

    service = HostGitOperationService(WorkspaceSandbox(tmp_path))
    approved_remote_url = service.remote_url(str(workspace))
    assert approved_remote_url == str(remote)

    result = service.push(
        str(workspace),
        branch=target_branch,
        commit_sha=approved_sha,
        expected_remote_url=approved_remote_url,
    )

    assert result.startswith("exit_code=0\n")
    assert git(
        "--git-dir", str(remote), "rev-parse", f"refs/heads/{target_branch}"
    ) == approved_sha
    refs = git("--git-dir", str(remote), "for-each-ref", "--format=%(refname)")
    assert refs.splitlines() == [f"refs/heads/{target_branch}"]
    assert not hook_marker.exists()
