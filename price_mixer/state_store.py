"""Safe JSON state file helpers.

Runtime state files are edited frequently by background tasks. Keep the
low-level file handling here so callers get consistent corrupted-file fallback
and atomic writes.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


MISSING = object()
_PATH_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}


def _path_lock(path: Path) -> threading.RLock:
    key = str(Path(path).resolve())
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def load_json(path: Path, default: Any = None, expected_type: type | tuple[type, ...] | None = None) -> Any:
    """Load JSON from ``path`` with a defensive fallback."""
    fallback = {} if default is None else default
    path = Path(path)
    if not path.exists():
        return fallback
    with _path_lock(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return fallback
    if expected_type is not None and not isinstance(data, expected_type):
        return fallback
    return data


def save_json_atomic(path: Path, data: Any) -> None:
    """Write JSON via a sibling temp file and atomic replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    with _path_lock(path):
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as f:
                tmp = Path(f.name)
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            _replace_with_retry(tmp, path)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)


def _replace_with_retry(source: Path, target: Path, attempts: int = 8) -> None:
    for attempt in range(max(1, int(attempts))):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt >= attempts - 1:
                raise
            time.sleep(0.01 * (attempt + 1))


def load_dict(path: Path) -> dict:
    return load_json(path, default={}, expected_type=dict)


def save_dict(path: Path, data: Any) -> None:
    save_json_atomic(path, data if isinstance(data, dict) else {})


def load_list(path: Path) -> list:
    return load_json(path, default=[], expected_type=list)


def save_list(path: Path, data: Any, limit: int | None = None) -> None:
    payload = data if isinstance(data, list) else []
    if limit is not None:
        payload = payload[-max(0, int(limit)):]
    save_json_atomic(path, payload)


def append_list_item(path: Path, item: Any, limit: int | None = None, sort_key=None, reverse: bool = False) -> list:
    path = Path(path)
    with _path_lock(path):
        rows = load_list(path)
        rows.append(item)
        if sort_key is not None:
            rows.sort(key=sort_key, reverse=reverse)
        save_list(path, rows, limit=limit)
        return rows
