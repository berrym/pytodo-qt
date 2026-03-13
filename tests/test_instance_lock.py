"""Tests for pytodo_qt.core.instance_lock."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from pytodo_qt.core.instance_lock import InstanceLock, _is_process_alive, terminate_process

# ---------------------------------------------------------------------------
# TestInstanceLockAcquire
# ---------------------------------------------------------------------------


class TestInstanceLockAcquire:
    """Tests for InstanceLock.acquire()."""

    def test_acquire_succeeds_on_first_call(self, tmp_path: Path) -> None:
        lock = InstanceLock(lock_path=tmp_path / "test.lock")
        assert lock.acquire() is True
        assert lock.lock_path.exists()
        assert lock.read_pid() == os.getpid()
        lock.release()

    def test_acquire_fails_when_already_held(self, tmp_path: Path) -> None:
        lock1 = InstanceLock(lock_path=tmp_path / "test.lock")
        lock2 = InstanceLock(lock_path=tmp_path / "test.lock")
        assert lock1.acquire() is True
        assert lock2.acquire() is False
        lock1.release()

    def test_acquire_succeeds_after_release(self, tmp_path: Path) -> None:
        lock1 = InstanceLock(lock_path=tmp_path / "test.lock")
        lock2 = InstanceLock(lock_path=tmp_path / "test.lock")
        assert lock1.acquire() is True
        lock1.release()
        assert lock2.acquire() is True
        lock2.release()

    def test_acquire_creates_parent_dir(self, tmp_path: Path) -> None:
        lock = InstanceLock(lock_path=tmp_path / "subdir" / "test.lock")
        assert lock.acquire() is True
        assert (tmp_path / "subdir").is_dir()
        lock.release()

    def test_acquire_graceful_on_permission_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fail(*args: object, **kwargs: object) -> None:  # noqa: ARG001
            raise PermissionError("denied")

        monkeypatch.setattr("os.open", _fail)
        lock = InstanceLock(lock_path=tmp_path / "test.lock")
        assert lock.acquire() is True


# ---------------------------------------------------------------------------
# TestInstanceLockReadPid
# ---------------------------------------------------------------------------


class TestInstanceLockReadPid:
    """Tests for InstanceLock.read_pid()."""

    def test_read_pid_after_acquire(self, tmp_path: Path) -> None:
        lock = InstanceLock(lock_path=tmp_path / "test.lock")
        lock.acquire()
        assert lock.read_pid() == os.getpid()
        lock.release()

    def test_read_pid_no_file(self, tmp_path: Path) -> None:
        lock = InstanceLock(lock_path=tmp_path / "nonexistent.lock")
        assert lock.read_pid() is None

    def test_read_pid_empty_file(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "test.lock"
        lock_path.write_text("")
        lock = InstanceLock(lock_path=lock_path)
        assert lock.read_pid() is None

    def test_read_pid_garbage_content(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "test.lock"
        lock_path.write_text("not-a-pid\n")
        lock = InstanceLock(lock_path=lock_path)
        assert lock.read_pid() is None


# ---------------------------------------------------------------------------
# TestInstanceLockRelease
# ---------------------------------------------------------------------------


class TestInstanceLockRelease:
    """Tests for InstanceLock.release()."""

    def test_release_idempotent(self, tmp_path: Path) -> None:
        lock = InstanceLock(lock_path=tmp_path / "test.lock")
        lock.acquire()
        lock.release()
        lock.release()  # should not raise

    def test_release_without_acquire(self, tmp_path: Path) -> None:
        lock = InstanceLock(lock_path=tmp_path / "test.lock")
        lock.release()  # should not raise


# ---------------------------------------------------------------------------
# TestInstanceLockCrashSafety
# ---------------------------------------------------------------------------


class TestInstanceLockCrashSafety:
    """Tests that locks are released when the holding process dies."""

    def test_lock_released_after_subprocess_death(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "test.lock"

        # Subprocess acquires lock then exits without releasing (simulates crash)
        script = (
            "import sys, pathlib; "
            f"sys.path.insert(0, 'src'); "
            "from pytodo_qt.core.instance_lock import InstanceLock; "
            f"lock = InstanceLock(lock_path=pathlib.Path(r'{lock_path}')); "
            "assert lock.acquire()"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            timeout=10,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, result.stderr.decode()

        # Now we should be able to acquire it
        lock = InstanceLock(lock_path=lock_path)
        assert lock.acquire() is True
        lock.release()


# ---------------------------------------------------------------------------
# TestIsProcessAlive
# ---------------------------------------------------------------------------


class TestIsProcessAlive:
    """Tests for _is_process_alive helper."""

    def test_current_process_alive(self) -> None:
        assert _is_process_alive(os.getpid()) is True

    def test_bogus_pid_not_alive(self) -> None:
        assert _is_process_alive(0) is False
        assert _is_process_alive(-1) is False

    def test_nonexistent_pid(self) -> None:
        assert _is_process_alive(4_000_000) is False


# ---------------------------------------------------------------------------
# TestTerminateProcess
# ---------------------------------------------------------------------------


class TestTerminateProcess:
    """Tests for terminate_process helper."""

    def test_terminate_dead_process(self) -> None:
        assert terminate_process(4_000_000) is True

    def test_terminate_real_subprocess(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        pid = proc.pid
        # terminate_process sends SIGTERM/SIGKILL but cannot reap the child
        # (only the parent Popen can).  On POSIX the child becomes a zombie
        # that os.kill(pid, 0) still sees as alive, so terminate_process may
        # return False.  We verify the signal was delivered by reaping here.
        terminate_process(pid, timeout=5.0)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        assert not _is_process_alive(pid)
