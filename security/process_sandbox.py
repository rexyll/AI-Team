"""Windows Job Object containment for Developer tool execution.

The terminal tool previously ran commands as a bare ``powershell.exe`` child:
a timeout killed only the direct child, leaving grandchildren orphaned, and a
command could exhaust memory or spawn unbounded process trees inside the
workspace. This module wraps the spawned process tree in a Win32 Job Object
(stdlib ctypes only - no new dependency) providing:

- per-process memory commit limit;
- maximum number of concurrently active processes in the tree;
- optional hard CPU-rate limit;
- kill-on-close: closing the job handle terminates every surviving process
  in the tree, including orphans a timeout would previously have left behind.

Containment note: the tree is assigned right after process creation. A child
that somehow spawns descendants between process creation and job assignment
(a microsecond window before PowerShell initializes) would escape the job;
no breakaway flags are granted, so all later descendants are contained.

Limits are host-configured through environment variables and default to
generous ceilings that catch runaway trees without constraining ordinary
builds: ``AI_TEAM_SANDBOX_MEMORY_MB`` (default 4096, 0 disables),
``AI_TEAM_SANDBOX_MAX_PROCESSES`` (default 128, 0 disables) and
``AI_TEAM_SANDBOX_CPU_RATE_PERCENT`` (unset disables CPU-rate control).
"""

from __future__ import annotations

import os
import sys
from typing import Any

JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_CPU_RATE_CONTROL = 0x00040000

JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x00000001
JOB_OBJECT_CPU_RATE_CONTROL_HARD_LIMIT = 0x00000002

JobObjectExtendedLimitInformation = 9
JobObjectCpuRateControlInformation = 21

PROCESS_SET_QUOTA = 0x0100
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000

DEFAULT_MEMORY_MB = 4096
DEFAULT_MAX_PROCESSES = 128

_is_windows = sys.platform == "win32"

if _is_windows:
    import ctypes
    from ctypes import wintypes

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("ControlFlags", wintypes.DWORD),
            ("CpuRate", wintypes.DWORD),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
else:  # pragma: no cover - non-Windows platforms never construct jobs
    _kernel32 = None


def process_job_supported() -> bool:
    """Return whether Job Object containment is available on this platform."""
    return _is_windows


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value


def _env_cpu_rate() -> int | None:
    raw = os.getenv("AI_TEAM_SANDBOX_CPU_RATE_PERCENT", "").strip()
    if not raw:
        return None
    try:
        percent = int(raw)
    except ValueError as exc:
        raise ValueError("AI_TEAM_SANDBOX_CPU_RATE_PERCENT must be an integer") from exc
    if not 1 <= percent <= 100:
        raise ValueError("AI_TEAM_SANDBOX_CPU_RATE_PERCENT must be within 1..100")
    return percent


class WindowsProcessJob:
    """One Job Object containing a single spawned command process tree."""

    def __init__(self) -> None:
        if not _is_windows:
            raise RuntimeError("Windows Job Objects are unavailable on this platform")
        memory_mb = _env_int("AI_TEAM_SANDBOX_MEMORY_MB", DEFAULT_MEMORY_MB)
        max_processes = _env_int("AI_TEAM_SANDBOX_MAX_PROCESSES", DEFAULT_MAX_PROCESSES)
        cpu_rate_percent = _env_cpu_rate()

        self._handle = _kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise OSError(f"CreateJobObjectW failed: {ctypes.get_last_error()}")

        try:
            limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if memory_mb:
                flags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY
                limits.ProcessMemoryLimit = memory_mb * 1024 * 1024
            if max_processes:
                flags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                limits.BasicLimitInformation.ActiveProcessLimit = max_processes
            limits.BasicLimitInformation.LimitFlags = flags
            if not _kernel32.SetInformationJobObject(
                self._handle,
                JobObjectExtendedLimitInformation,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                raise OSError(
                    f"SetInformationJobObject failed: {ctypes.get_last_error()}"
                )

            if cpu_rate_percent is not None:
                rate = _JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
                rate.ControlFlags = (
                    JOB_OBJECT_CPU_RATE_CONTROL_ENABLE
                    | JOB_OBJECT_CPU_RATE_CONTROL_HARD_LIMIT
                )
                rate.CpuRate = cpu_rate_percent * 100
                # CPU-rate control requires Windows 8+; a failure here only
                # means the optional CPU ceiling is unavailable, not fatal.
                _kernel32.SetInformationJobObject(
                    self._handle,
                    JobObjectCpuRateControlInformation,
                    ctypes.byref(rate),
                    ctypes.sizeof(rate),
                )
        except Exception:
            self._close()
            raise

    def assign(self, process: Any) -> None:
        """Place an already-spawned process (and its descendants) in the job.

        ``process`` is a ``subprocess.Popen``; its internal handle carries the
        access rights required for assignment.
        """
        if not _kernel32.AssignProcessToJobObject(self._handle, int(process._handle)):
            raise OSError(f"AssignProcessToJobObject failed: {ctypes.get_last_error()}")

    def terminate(self, exit_code: int = 1) -> None:
        """Terminate every process currently in the job."""
        if not _kernel32.TerminateJobObject(self._handle, exit_code):
            raise OSError(f"TerminateJobObject failed: {ctypes.get_last_error()}")

    def _close(self) -> None:
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = None

    def close(self) -> None:
        """Close the job handle; kill-on-close terminates any surviving tree."""
        self._close()

    def __enter__(self) -> "WindowsProcessJob":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def create_process_job() -> WindowsProcessJob | None:
    """Return a configured job, or None where Job Objects are unavailable."""
    if not process_job_supported():
        return None
    return WindowsProcessJob()


def wait_for_process_exit(pid: int, timeout_ms: int = 5000) -> bool:
    """Best-effort liveness probe used by regression tests for tree kills."""
    if not _is_windows:
        raise RuntimeError("process liveness probing is Windows-only")
    handle = _kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        # The process either already exited or the pid was recycled; both
        # satisfy the caller's question quickly enough for containment checks.
        return True
    try:
        return _kernel32.WaitForSingleObject(handle, timeout_ms) == WAIT_OBJECT_0
    finally:
        _kernel32.CloseHandle(handle)
