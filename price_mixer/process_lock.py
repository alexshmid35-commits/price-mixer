"""Small pid-file lock for single-run background workers."""

from __future__ import annotations

import atexit
import os
from pathlib import Path


class PidFileLock:
    """Owns a pid lock file until released or process exit."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            if self.path.exists() and self.path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                self.path.unlink()
        except OSError:
            pass


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        process_query_limited_information = 0x1000
        handle = open_process(process_query_limited_information, False, int(pid))
        if handle:
            close_handle(handle)
            return True
        # Access denied still proves that the process exists.
        return ctypes.get_last_error() == 5
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def try_acquire_pid_lock(path: Path) -> PidFileLock | None:
    """Acquire ``path`` as a pid-file lock, cleaning stale locks when possible."""
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    for _ in range(2):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                existing = int(lock_path.read_text(encoding="utf-8").strip() or "0")
            except (OSError, ValueError):
                existing = 0
            if _pid_is_running(existing):
                return None
            try:
                lock_path.unlink()
            except OSError:
                return None
            continue

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        lock = PidFileLock(lock_path)
        atexit.register(lock.release)
        return lock

    return None
