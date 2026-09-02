from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable
from uuid import uuid4

from runtime.workflow_event import WorkflowEvent
from runtime.workflow_event_log import WorkflowEventLog
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
    execution_id: str

    def as_dict(self) -> dict[str, object]:
        return {"command": self.command, "cwd": self.cwd, "output": self.output, "exit_code": self.exit_code, "timed_out": self.timed_out, "truncated": self.truncated, "execution_id": self.execution_id}


@dataclass(frozen=True)
class _TerminalExecution:
    execution_id: str
    command: str
    cwd: str
    started_at: str
    status: str
    completed_at: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    truncated: bool = False
    error_type: str | None = None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"execution_id": self.execution_id, "command": self.command, "cwd": self.cwd, "status": self.status, "started_at": self.started_at, "timed_out": self.timed_out, "truncated": self.truncated}
        if self.completed_at is not None:
            result["completed_at"] = self.completed_at
        if self.exit_code is not None:
            result["exit_code"] = self.exit_code
        if self.error_type is not None:
            result["error_type"] = self.error_type
        return result


TerminalAuditSink = Callable[[MCPTerminalResult], None]


class MCPTerminalCapabilityBoundary:
    """Expose the existing allow-listed terminal policy through MCP.

    The execution registry is an ephemeral control-plane projection, not a
    second audit store. When configured, the canonical WorkflowEventLog keeps
    the durable lifecycle events.
    """

    def __init__(self, workspace_root: str, *, audit_sink: TerminalAuditSink | None = None, workflow_event_log: WorkflowEventLog | None = None, project_id: str | None = None) -> None:
        if workflow_event_log is not None and not isinstance(workflow_event_log, WorkflowEventLog):
            raise TypeError("workflow_event_log must be a WorkflowEventLog or None")
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise ValueError("project_id must be a non-empty string or None")
        if workflow_event_log is not None and not project_id:
            raise ValueError("project_id is required when workflow_event_log is configured")
        if project_id and workflow_event_log is None:
            raise ValueError("project_id requires workflow_event_log")
        self._sandbox = WorkspaceSandbox(workspace_root)
        self._audit_sink = audit_sink
        self._workflow_event_log = workflow_event_log
        self._project_id = project_id.strip() if isinstance(project_id, str) else project_id
        self._executions: dict[str, _TerminalExecution] = {}
        self._executions_lock = Lock()

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

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _emit_event(self, event_type: str, *, execution_id: str, cwd: str, payload: dict[str, object]) -> None:
        if self._workflow_event_log is None or not self._project_id:
            return
        self._workflow_event_log.append(WorkflowEvent(event_id=str(uuid4()), event_type=event_type, project_id=self._project_id, occurred_at=self._timestamp(), payload={"source": "mcp", "execution_id": execution_id, "cwd": cwd, **payload}))

    def _register(self, record: _TerminalExecution) -> None:
        with self._executions_lock:
            self._executions[record.execution_id] = record

    def _update(self, execution_id: str, **changes: Any) -> _TerminalExecution:
        with self._executions_lock:
            current = self._executions[execution_id]
            updated = replace(current, **changes)
            self._executions[execution_id] = updated
            return updated

    def execution_status(self, execution_id: str) -> dict[str, object]:
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise ValueError("execution_id must be a non-empty string")
        normalized_id = execution_id.strip()
        with self._executions_lock:
            record = self._executions.get(normalized_id)
        if record is None:
            raise KeyError(f"Unknown terminal execution id: {normalized_id}")
        return record.as_dict()

    def execution_history(self, *, limit: int = 50) -> list[dict[str, object]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        with self._executions_lock:
            records = sorted(self._executions.values(), key=lambda item: item.started_at)
        return [record.as_dict() for record in records[-limit:]]

    def execute(self, command: str, cwd: str = ".", *, timeout: float = DEFAULT_TIMEOUT_SECONDS, max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS) -> dict[str, object]:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        self._validate_command_shape(command)
        normalized_timeout = self._validate_timeout(timeout)
        output_limit = self._validate_output_limit(max_output_chars)
        resolved = self._sandbox.resolve(cwd or ".")
        relative_cwd = resolved.relative_to(self._sandbox.root).as_posix() or "."
        if not resolved.is_dir():
            raise NotADirectoryError(f"Terminal cwd must be a directory: {relative_cwd}")

        execution_id = str(uuid4())
        self._register(_TerminalExecution(execution_id, command, relative_cwd, self._timestamp(), "active"))
        self._emit_event("mcp_terminal_execution_requested", execution_id=execution_id, cwd=relative_cwd, payload={"command": command, "timeout": normalized_timeout, "max_output_chars": output_limit, "status": "active"})
        try:
            raw = run_command(command, relative_cwd, sandbox=self._sandbox, timeout=normalized_timeout)
            exit_code, output = self._parse_output(raw)
            timed_out = exit_code == 124
            truncated = len(output) > output_limit
            bounded_output = output[:output_limit]
            if truncated:
                bounded_output += "\n[output truncated by MCP terminal boundary]"
            result = MCPTerminalResult(command, relative_cwd, bounded_output, exit_code, timed_out, truncated, execution_id)
            if self._audit_sink is not None:
                self._audit_sink(result)
            status = "completed" if exit_code == 0 else "failed"
            self._update(execution_id, status=status, completed_at=self._timestamp(), exit_code=exit_code, timed_out=timed_out, truncated=truncated)
            self._emit_event("mcp_terminal_execution_completed", execution_id=execution_id, cwd=relative_cwd, payload={"command": command, "exit_code": exit_code, "timed_out": timed_out, "truncated": truncated, "status": status})
            return result.as_dict()
        except Exception as exc:
            self._update(execution_id, status="failed", completed_at=self._timestamp(), error_type=type(exc).__name__)
            self._emit_event("mcp_terminal_execution_failed", execution_id=execution_id, cwd=relative_cwd, payload={"command": command, "error_type": type(exc).__name__, "status": "failed"})
            raise
