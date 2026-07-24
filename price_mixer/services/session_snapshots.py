"""Coalesced compatibility snapshots for SQL-backed working sessions."""

from __future__ import annotations

import threading
from pathlib import Path


class CompatibilitySnapshotWriter:
    """Debounce JSON writes while keeping SQLite mutations synchronous."""

    def __init__(self, write_rows, *, delay_seconds=0.2):
        self.write_rows = write_rows
        self.delay_seconds = max(0.0, float(delay_seconds))
        self._lock = threading.RLock()
        self._pending = {}
        self._timers = {}

    def schedule(self, session_dir, rows):
        session_path = Path(session_dir).resolve()
        key = str(session_path)
        copied_rows = [list(row) for row in rows or []]
        with self._lock:
            self._pending[key] = (session_path, copied_rows)
            timer = self._timers.pop(key, None)
            if timer is not None:
                timer.cancel()
            timer = threading.Timer(self.delay_seconds, self._flush_key, args=(key,))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()
        return {"state": "queued", "rows": len(copied_rows)}

    def flush(self, session_dir):
        self._flush_key(str(Path(session_dir).resolve()))

    def flush_all(self):
        with self._lock:
            keys = list(self._pending)
        for key in keys:
            self._flush_key(key)

    def _flush_key(self, key):
        with self._lock:
            timer = self._timers.pop(key, None)
            if timer is not None and timer is not threading.current_thread():
                timer.cancel()
            pending = self._pending.pop(key, None)
        if pending is None:
            return
        session_path, rows = pending
        self.write_rows(rows, session_path / "consolidated.json")
