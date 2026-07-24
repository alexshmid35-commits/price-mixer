from pathlib import Path

from price_mixer.services.upload_sessions import (
    cleanup_old_uploads,
    create_session_dir,
    maybe_cleanup_old_uploads,
)


def _touch_dir(path: Path, marker: str | None = None, mtime: float = 0) -> Path:
    path.mkdir()
    if marker:
        (path / marker).write_text("x", encoding="utf-8")
    path.touch()
    for child in path.iterdir():
        child.touch()
    path.parent.joinpath(path.name).touch()
    import os

    os.utime(path, (mtime, mtime))
    return path


def test_create_session_dir_creates_short_id_directory(tmp_path):
    session_id, session_dir = create_session_dir(tmp_path)

    assert len(session_id) == 8
    assert session_dir == tmp_path / session_id
    assert session_dir.is_dir()


def test_cleanup_old_uploads_keeps_recent_sessions_and_removes_old_api_dirs(tmp_path):
    old = 1_000_000.0
    settings = {
        "uploads_cleanup": {
            "keep_last_sessions": 1,
            "keep_days": 1,
            "keep_api_fetch_hours": 1,
        }
    }
    keep_session = _touch_dir(tmp_path / "keep", "consolidated.json", old)
    remove_session = _touch_dir(tmp_path / "remove", "consolidated.json", old - 10)
    remove_api = _touch_dir(tmp_path / "_api_fetch_old", None, old - 10)
    excluded = _touch_dir(tmp_path / "excluded", "consolidated.json", old - 20)

    result = cleanup_old_uploads(
        tmp_path,
        load_settings=lambda: settings,
        exclude_dirs=[excluded],
        now=old + 3 * 24 * 3600,
    )

    assert result == {"removed": 2, "skipped": 0}
    assert keep_session.exists()
    assert excluded.exists()
    assert not remove_session.exists()
    assert not remove_api.exists()


def test_maybe_cleanup_old_uploads_throttles_by_timestamp():
    called = {"count": 0}

    def cleanup():
        called["count"] += 1
        return {"removed": 1, "skipped": 0}

    throttled, last_ts = maybe_cleanup_old_uploads(
        cleanup=cleanup,
        last_cleanup_ts=100,
        min_interval_sec=60,
        now=120,
    )
    executed, next_ts = maybe_cleanup_old_uploads(
        cleanup=cleanup,
        last_cleanup_ts=last_ts,
        min_interval_sec=60,
        now=200,
    )

    assert throttled == {"removed": 0, "skipped": 0, "throttled": True}
    assert executed == {"removed": 1, "skipped": 0, "throttled": False}
    assert next_ts == 200
    assert called["count"] == 1
