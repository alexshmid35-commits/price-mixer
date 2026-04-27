"""Thread-safe JSON cache with optional TTL."""

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional


class JsonCache:
    """Disk-backed JSON cache with in-memory buffering and TTL support."""

    def __init__(self, path: Path, ttl_seconds: Optional[int] = None):
        self.path = Path(path)
        self.ttl = ttl_seconds
        self._lock = threading.RLock()
        self._data: Optional[Dict[str, Any]] = None
        self._loaded_at = 0.0

    def _load(self) -> Dict[str, Any]:
        with self._lock:
            if self._data is not None:
                return self._data
            if self.path.exists():
                try:
                    with open(self.path, "r", encoding="utf-8") as f:
                        self._data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    self._data = {}
            else:
                self._data = {}
            self._loaded_at = time.time()
            return self._data

    def _save(self) -> None:
        with self._lock:
            if self._data is None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            tmp.replace(self.path)

    def get(self, key: str, default: Any = None) -> Any:
        data = self._load()
        with self._lock:
            item = data.get(key)
            if item is None:
                return default
            if self.ttl is not None and isinstance(item, dict) and "_cached_at" in item:
                if time.time() - item["_cached_at"] > self.ttl:
                    data.pop(key, None)
                    self._save()
                    return default
            return item

    def set(self, key: str, value: Any, with_timestamp: bool = False) -> None:
        data = self._load()
        with self._lock:
            if with_timestamp and isinstance(value, dict):
                value = dict(value)
                value["_cached_at"] = time.time()
            data[key] = value
            self._save()

    def pop(self, key: str, default: Any = None) -> Any:
        data = self._load()
        with self._lock:
            result = data.pop(key, default)
            self._save()
            return result

    def keys(self):
        data = self._load()
        with self._lock:
            return list(data.keys())

    def values(self):
        data = self._load()
        with self._lock:
            return list(data.values())

    def items(self):
        data = self._load()
        with self._lock:
            return list(data.items())

    def clear(self) -> None:
        with self._lock:
            self._data = {}
            self._save()

    def prune_expired(self) -> int:
        if self.ttl is None:
            return 0
        data = self._load()
        now = time.time()
        removed = 0
        with self._lock:
            keys = list(data.keys())
            for k in keys:
                item = data.get(k)
                if isinstance(item, dict) and "_cached_at" in item:
                    if now - item["_cached_at"] > self.ttl:
                        data.pop(k, None)
                        removed += 1
            if removed:
                self._save()
        return removed
