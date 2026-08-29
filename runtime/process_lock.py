from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def exclusive_process_lock(path: str | Path) -> Iterator[None]:
    """Hold an OS-level advisory lock for the duration of one critical section.

    On Windows the lock byte is provisioned before opening the file for
    read/write. This is important for concurrent ``spawn`` processes: the
    previous implementation opened ``a+b`` and wrote the sentinel byte before
    acquiring the lock, so a contending process could receive a sharing/access
    error while both processes were racing to initialize the same lock file.
    """
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        import msvcrt

        # Provision exactly one byte without holding the file open. Opening the
        # existing file as r+b below avoids an unlocked write in the critical
        # initialization window.
        lock_path.touch(exist_ok=True)
        with lock_path.open("r+b") as handle:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
