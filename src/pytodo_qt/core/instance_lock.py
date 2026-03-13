"""instance_lock.py

Single-instance guard using file-descriptor-based locking.

POSIX: fcntl.flock() — auto-releases on process death.
Windows: msvcrt.locking() — auto-releases on process death.
"""

from __future__ import annotations

import os
import sys
import time as _time_mod
from pathlib import Path

from .logger import Logger
from .paths import get_state_dir

logger = Logger(__name__)

_LOCK_FILENAME = "pytodo-qt.lock"


class InstanceLock:
    """File-based single-instance lock.

    The lock is held via an open file descriptor with an OS-level
    exclusive lock.  If the process crashes, the OS closes all file
    descriptors and the lock is automatically released.
    """

    def __init__(self, lock_path: Path | None = None) -> None:
        self._lock_path = lock_path or (get_state_dir() / _LOCK_FILENAME)
        self._fd: int | None = None

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    def acquire(self) -> bool:
        """Try to acquire the instance lock.

        Returns True if the lock was acquired (no other instance running).
        Returns False if another instance holds the lock.
        """
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            fd = os.open(str(self._lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as e:
            logger.log.warning("Cannot open lock file %s: %s", self._lock_path, e)
            return True

        if not self._try_lock(fd):
            os.close(fd)
            return False

        self._fd = fd
        self._write_pid(fd)
        logger.log.info("Instance lock acquired (PID %d)", os.getpid())
        return True

    def read_pid(self) -> int | None:
        """Read the PID from the lock file without acquiring the lock.

        If *we* hold the lock, read directly via our file descriptor
        (Windows byte-range locks block other opens).  Otherwise fall
        back to a normal file read.
        """
        if self._fd is not None:
            try:
                os.lseek(self._fd, 0, os.SEEK_SET)
                data = os.read(self._fd, 64)
                text = data.decode().strip()
                if text:
                    return int(text)
            except (OSError, ValueError):
                pass
            return None

        try:
            text = self._lock_path.read_text().strip()
            if text:
                return int(text)
        except (OSError, ValueError):
            pass
        return None

    def release(self) -> None:
        """Explicitly release the lock.  Idempotent."""
        if self._fd is not None:
            try:
                self._try_unlock(self._fd)
                os.close(self._fd)
                logger.log.info("Instance lock released")
            except OSError as e:
                logger.log.warning("Error releasing instance lock: %s", e)
            finally:
                self._fd = None

    # -- Platform-specific internals ----------------------------------

    @staticmethod
    def _try_lock(fd: int) -> bool:
        if sys.platform == "win32":
            import msvcrt

            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        else:
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                return False

    @staticmethod
    def _try_unlock(fd: int) -> None:
        if sys.platform == "win32":
            import msvcrt

            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)

    @staticmethod
    def _write_pid(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        os.fsync(fd)


def terminate_process(pid: int, timeout: float = 3.0) -> bool:
    """Terminate process *pid* gracefully, then forcefully.

    Returns True if the process is confirmed dead (or was already dead).
    """
    if not _is_process_alive(pid):
        return True

    try:
        if sys.platform == "win32":
            import subprocess

            subprocess.run(
                ["taskkill", "/PID", str(pid)],
                capture_output=True,
                timeout=timeout,
            )
        else:
            import signal

            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass

    deadline = _time_mod.monotonic() + timeout
    while _time_mod.monotonic() < deadline:
        if not _is_process_alive(pid):
            return True
        _time_mod.sleep(0.1)

    # Escalate to force kill
    try:
        if sys.platform == "win32":
            import subprocess

            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=2.0,
            )
        else:
            import signal

            os.kill(pid, signal.SIGKILL)
    except Exception:
        pass

    # Give the OS time to reclaim the process handle (Windows needs more)
    deadline2 = _time_mod.monotonic() + 2.0
    while _time_mod.monotonic() < deadline2:
        if not _is_process_alive(pid):
            return True
        _time_mod.sleep(0.1)
    return not _is_process_alive(pid)


def _is_process_alive(pid: int) -> bool:
    """Check whether *pid* refers to a running process."""
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000  # noqa: N806
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
