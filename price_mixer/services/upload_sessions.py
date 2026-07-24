"""Upload session housekeeping helpers."""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path
from typing import Callable, Iterable


def create_session_dir(upload_dir: Path) -> tuple[str, Path]:
    session_id = str(uuid.uuid4())[:8]
    session_dir = Path(upload_dir) / session_id
    session_dir.mkdir(exist_ok=True)
    return session_id, session_dir


def cleanup_old_uploads(
    upload_dir: Path,
    *,
    load_settings: Callable[[], dict],
    exclude_dirs: Iterable[str | Path] | None = None,
    keep_last_sessions_default: int = 20,
    keep_days_default: int = 7,
    keep_api_fetch_hours_default: int = 12,
    now: float | None = None,
) -> dict:
    exclude = {str(Path(p).resolve()) for p in (exclude_dirs or []) if p}
    current_ts = time.time() if now is None else float(now)
    cleanup_cfg = (load_settings().get("uploads_cleanup") or {})
    keep_last_sessions = int(
        cleanup_cfg.get("keep_last_sessions", keep_last_sessions_default) or keep_last_sessions_default
    )
    keep_days = int(cleanup_cfg.get("keep_days", keep_days_default) or keep_days_default)
    keep_api_fetch_hours = int(
        cleanup_cfg.get("keep_api_fetch_hours", keep_api_fetch_hours_default) or keep_api_fetch_hours_default
    )
    keep_session_sec = keep_days * 24 * 3600
    keep_api_sec = keep_api_fetch_hours * 3600
    try:
        dirs = [p for p in Path(upload_dir).iterdir() if p.is_dir()]
    except Exception:
        return {"removed": 0, "skipped": 0}

    session_dirs = []
    api_fetch_dirs = []
    other_dirs = []
    for path in dirs:
        resolved = str(path.resolve())
        if resolved in exclude:
            continue
        if path.name.startswith("_api_fetch_"):
            api_fetch_dirs.append(path)
        elif (path / "consolidated_price.xlsx").exists() or (path / "consolidated.json").exists():
            session_dirs.append(path)
        else:
            other_dirs.append(path)

    removed = 0
    skipped = 0

    session_dirs.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    for idx, path in enumerate(session_dirs):
        try:
            mtime = path.stat().st_mtime
        except Exception:
            skipped += 1
            continue
        age = current_ts - mtime
        if idx < keep_last_sessions:
            continue
        if age < keep_session_sec:
            continue
        try:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except Exception:
            skipped += 1

    for path in api_fetch_dirs + other_dirs:
        try:
            mtime = path.stat().st_mtime
        except Exception:
            skipped += 1
            continue
        age = current_ts - mtime
        if age < keep_api_sec:
            continue
        try:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except Exception:
            skipped += 1

    return {"removed": removed, "skipped": skipped}


def maybe_cleanup_old_uploads(
    *,
    cleanup: Callable[[], dict],
    last_cleanup_ts: float,
    min_interval_sec: float = 1800,
    now: float | None = None,
) -> tuple[dict, float]:
    current_ts = time.time() if now is None else float(now)
    if current_ts - float(last_cleanup_ts or 0) < float(min_interval_sec or 0):
        return {"removed": 0, "skipped": 0, "throttled": True}, last_cleanup_ts
    result = cleanup()
    result["throttled"] = False
    return result, current_ts
