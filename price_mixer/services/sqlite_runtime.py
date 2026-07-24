"""Shared SQLite connection policy and scheduled maintenance helpers."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

BUSY_TIMEOUT_MS = 30_000
ANALYSIS_LIMIT = 1_000

_WAL_LOCK = threading.Lock()
_WAL_DATABASES: set[tuple[str, int, int]] = set()


def connect_sqlite(
    path,
    *,
    timeout=30,
    check_same_thread=True,
    row_factory=None,
    wal=True,
    foreign_keys=False,
):
    """Open SQLite with the same concurrency policy across application stores."""
    database_path = Path(path).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        str(database_path),
        timeout=max(1.0, float(timeout)),
        check_same_thread=bool(check_same_thread),
    )
    if row_factory is not None:
        connection.row_factory = row_factory
    connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    if wal:
        _ensure_wal(connection, database_path)
        connection.execute("PRAGMA synchronous=NORMAL")
    if foreign_keys:
        connection.execute("PRAGMA foreign_keys=ON")
    return connection


def maintain_sqlite_database(
    path,
    *,
    checkpoint_mode="PASSIVE",
    optimize=True,
):
    """Checkpoint and refresh planner statistics outside request handlers."""
    database_path = Path(path).resolve()
    if not database_path.is_file():
        return {
            "path": str(database_path),
            "status": "missing",
        }
    mode = str(checkpoint_mode or "PASSIVE").strip().upper()
    if mode not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
        raise ValueError("unsupported SQLite checkpoint mode")
    with connect_sqlite(database_path, wal=True) as connection:
        checkpoint = connection.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
        if optimize:
            connection.execute(f"PRAGMA analysis_limit={ANALYSIS_LIMIT}")
            connection.execute("PRAGMA optimize")
    values = list(checkpoint or (0, 0, 0))
    while len(values) < 3:
        values.append(0)
    return {
        "path": str(database_path),
        "status": "ok",
        "checkpoint_mode": mode.lower(),
        "busy": int(values[0] or 0),
        "wal_pages": int(values[1] or 0),
        "checkpointed_pages": int(values[2] or 0),
        "optimized": bool(optimize),
    }


def maintain_runtime_databases(data_dir, *, names=None):
    """Maintain known runtime databases and return a diagnostic summary."""
    selected = tuple(names or ("onliner_products.db", "session_products.db", "jobs.db"))
    return [maintain_sqlite_database(Path(data_dir) / name) for name in selected]


def reset_sqlite_runtime_state():
    """Clear process-local initialization state for isolated tests."""
    with _WAL_LOCK:
        _WAL_DATABASES.clear()


def _ensure_wal(connection, database_path):
    stat = database_path.stat()
    key = (str(database_path), int(stat.st_dev), int(stat.st_ino))
    if key in _WAL_DATABASES:
        return
    with _WAL_LOCK:
        if key in _WAL_DATABASES:
            return
        connection.execute("PRAGMA journal_mode=WAL")
        _WAL_DATABASES.add(key)
