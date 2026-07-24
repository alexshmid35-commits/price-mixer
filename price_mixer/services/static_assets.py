"""Content-versioned URLs and cache policy for local static assets."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path, PurePosixPath


class StaticAssetRegistry:
    def __init__(self, root, *, digest_length=12):
        self.root = Path(root).resolve()
        self.digest_length = max(8, int(digest_length))
        self._lock = threading.RLock()
        self._cache = {}

    def version(self, relative_path):
        path = self._resolve(relative_path)
        try:
            stat = path.stat()
        except OSError:
            return "missing"
        signature = (int(stat.st_mtime_ns), int(stat.st_size))
        key = str(path)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached[0] == signature:
                return cached[1]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[: self.digest_length]
        with self._lock:
            self._cache[key] = (signature, digest)
        return digest

    def is_current(self, relative_path, version):
        requested = str(version or "").strip()
        return bool(requested) and requested == self.version(relative_path)

    def invalidate(self):
        with self._lock:
            self._cache.clear()

    def _resolve(self, relative_path):
        normalized = PurePosixPath(str(relative_path or "").lstrip("/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("invalid static asset path")
        path = (self.root / Path(*normalized.parts)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("static asset escapes root")
        return path
