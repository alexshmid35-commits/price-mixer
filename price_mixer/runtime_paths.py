"""Central runtime directory layout with legacy-compatible defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RuntimePaths:
    project_root: Path
    state_dir: Path
    data_dir: Path
    cache_dir: Path
    uploads_dir: Path
    logs_dir: Path

    def state_file(self, name):
        return self.state_dir / str(name)

    def data_file(self, name):
        return self.data_dir / str(name)

    def cache_file(self, name):
        return self.cache_dir / str(name)


def load_runtime_paths(environ=None, *, project_root=None):
    """Resolve runtime paths; missing env keeps the historical layout."""
    env = os.environ if environ is None else environ
    root = Path(project_root or PROJECT_ROOT).resolve()
    return RuntimePaths(
        project_root=root,
        state_dir=_directory(env, "PRICE_MIXER_STATE_DIR", root, root),
        data_dir=_directory(env, "PRICE_MIXER_DATA_DIR", root, root),
        cache_dir=_directory(env, "PRICE_MIXER_CACHE_DIR", root, root),
        uploads_dir=_directory(
            env,
            "PRICE_MIXER_UPLOAD_DIR",
            root / "uploads",
            root,
        ),
        logs_dir=_directory(
            env,
            "PRICE_MIXER_LOG_DIR",
            root / "logs",
            root,
        ),
    )


def ensure_runtime_directories(paths=None):
    """Create only the configured runtime directories."""
    paths = paths or get_runtime_paths()
    for path in {
        paths.state_dir,
        paths.data_dir,
        paths.cache_dir,
        paths.uploads_dir,
        paths.logs_dir,
    }:
        path.mkdir(parents=True, exist_ok=True)
    return paths


def get_runtime_paths():
    return RUNTIME_PATHS


def _directory(environ, key, legacy_default, project_root):
    raw = str(environ.get(key, "") or "").strip()
    path = Path(raw) if raw else Path(legacy_default)
    if not path.is_absolute():
        path = Path(project_root) / path
    return path.resolve()


RUNTIME_PATHS = load_runtime_paths()
