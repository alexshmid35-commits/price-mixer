"""Unit tests for pid-file locking."""

import os

from price_mixer.process_lock import try_acquire_pid_lock


def test_try_acquire_pid_lock_creates_and_releases_lock(tmp_path):
    path = tmp_path / "worker.pid"

    lock = try_acquire_pid_lock(path)

    assert lock is not None
    assert path.read_text(encoding="utf-8") == str(os.getpid())

    lock.release()
    assert not path.exists()


def test_try_acquire_pid_lock_returns_none_for_running_pid(tmp_path):
    path = tmp_path / "worker.pid"
    path.write_text(str(os.getpid()), encoding="utf-8")

    assert try_acquire_pid_lock(path) is None
    assert path.read_text(encoding="utf-8") == str(os.getpid())


def test_try_acquire_pid_lock_replaces_stale_pid(tmp_path):
    path = tmp_path / "worker.pid"
    path.write_text("999999999", encoding="utf-8")

    lock = try_acquire_pid_lock(path)

    assert lock is not None
    assert path.read_text(encoding="utf-8") == str(os.getpid())
    lock.release()
