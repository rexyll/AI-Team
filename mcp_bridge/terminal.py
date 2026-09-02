from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from security.workspace import WorkspaceSandbox
from tools.terminal import run_command


DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_OUTPUT_CHARS = 64 * 1024
MAX_OUTPUT_CHARS = 512 * 1024


@dataclass(frozen=True)
class MCPTerminalResult:
    """Bounded result returned by the MCP terminal capability."""

    command: str
    cwd: str
    output: str
    exit_code: int
    timed_out: bool
    truncated: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "command": self.command,
            "cwd": self.cwd,
            "output": self.output,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "truncated": self.truncated,
        }


TerminalAuditSink = Callable[[MCPTerminalResult], None]


class MCPTerminalCapabilityBoundary:
    """Expose only the existing allow-listed terminal policy through MCP."""

    def __init__(
        self,
        workspace_root: str,
        *,
        audit_sink: TerminalAuditSink | None = None,
    ) -> None:
        self._sandbox = WorkspaceSandbox(workspace_root)
        self._audit_sink = audit_sink

    @staticmethod
    def _validate_timeout(timeout: float) -> float:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout must be a number")
        if timeout <= 0 or timeout > MAX_TIMEOUT_SECONDS:
            raise ValueError(f"timeout must be between 0 and {MAX_TIMEOUT_SECONDS} seconds")
        return float(timeout)

    @staticmethod
    def _validate_output_limit(max_output_chars: int) -> int:
        if isinstance(max_output_chars, bool) or not isinstance(max_output_chars, int):
            raise ValueError("max_output_chars must be an integer")
        if max_output_chars < 1 or max_output_chars > MAX_OUTPUT_CHARS:
            raise ValueError(f"max_output_chars must be between 1 and {MAX_OUTPUT_CHARS}")
        return max_output_chars

    @staticmethod
    def _validate_command_shape(command: str) -> None:
        if "\n" in command or "\r" in command:
            raise PermissionError("Multi-line terminal commands are not allowed")

    @staticmethod
    def _parse_output(raw: str) -> tuple[int, str]:
        first_line, separator, remainder = raw.partition("\n")
        if not separator or not first_line.startswith("exit_code="):
            raise RuntimeError("terminal backend returned an invalid result")
        try:
            exit_code = int(first_line.split("=", 1)[1])
        except ValueError as exc:
            raise RuntimeError("terminal backend returned an invalid exit code") from exc
        return exit_code, remainder

    def execute(
        self,
        command: str,
        cwd: str = ".",
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    ) -> dict[str, object]:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        self._validate_command_shape(command)
        normalized_timeout = self._validate_timeout(timeout)
        output_limit = self._validate_output_limit(max_output_chars)
        resolved = self._sandbox.resolve(cwd or ".")
        if not resolved.is_dir():
            relative_cwd = resolved.relative_to(self._sandbox.root).as_posix() or "."
            raise NotADirectoryError(f"Terminal cwd must be a directory: {relative_cwd}")

        relative_cwd = resolved.relative_to(self._sandbox.root).as_posix() or "."
        raw = run_command(
            command,
            relative_cwd,
            sandbox=self._sandbox,
            timeout=normalized_timeout,
        )
        exit_code, output = self._parse_output(raw)
        timed_out = exit_code == 124
        truncated = len(output) > output_limit
        bounded_output = output[:output_limit]
        if truncated:
            bounded_output += "\n[output truncated by MCP terminal boundary]"
        result = MCPTerminalResult(command, relative_cwd, bounded_output, exit_code, timed_out, truncated)
        if self._audit_sink is not None:
            self._audit_sink(result)
        return result.as_dict()
