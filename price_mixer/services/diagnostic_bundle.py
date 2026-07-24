"""Create a minimal diagnostic archive without user state or secrets."""

from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from price_mixer.services.runtime_hygiene import ARTIFACT_POLICIES


APPLICATION_VERSION = "2.0.0-refactor"
_DEPENDENCIES = ("Flask", "numpy", "openpyxl", "pandas", "requests")
_README = """Price Mixer diagnostic bundle

This archive contains aggregate runtime metadata only.
It deliberately excludes environment values, credentials, log contents,
state JSON contents, database rows, upload names and user data.
"""


def create_diagnostic_bundle(root, destination, *, environ=None):
    """Create a small ZIP diagnostic bundle and refuse overwrites."""
    root = Path(root).resolve()
    destination = Path(destination).resolve()
    if not root.is_dir():
        raise ValueError("project root must be an existing directory")
    if destination.exists():
        raise FileExistsError(f"diagnostic destination already exists: {destination}")

    snapshot = build_diagnostic_snapshot(root, environ=environ)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".price-mixer-diagnostics-",
            suffix=".zip",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        with zipfile.ZipFile(
            temporary_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr(
                "diagnostics.json",
                json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
            )
            archive.writestr("README.txt", _README)
        os.link(temporary_path, destination)
        temporary_path.unlink()
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return snapshot


def build_diagnostic_snapshot(root, *, environ=None):
    """Collect only allow-listed, aggregate diagnostic metadata."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("project root must be an existing directory")
    env = os.environ if environ is None else environ
    disk = shutil.disk_usage(root)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "application": {
            "service": "price-mixer",
            "version": APPLICATION_VERSION,
        },
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "system_release": platform.release(),
        },
        "dependencies": _dependency_versions(),
        "configuration": _safe_configuration(env),
        "filesystem": {
            "disk_total_bytes": disk.total,
            "disk_free_bytes": disk.free,
            "declared_artifacts": _declared_artifact_summary(root),
            "logs": _directory_summary(root / "logs"),
            "uploads": _directory_summary(root / "uploads"),
            "backups": _directory_summary(root / "backups"),
        },
        "database": _database_summary(root / "onliner_products.db"),
        "privacy": {
            "environment_values_included": False,
            "log_contents_included": False,
            "state_contents_included": False,
            "database_rows_included": False,
            "user_paths_included": False,
        },
    }


def _dependency_versions():
    versions = {}
    for package in _DEPENDENCIES:
        try:
            versions[package.lower()] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package.lower()] = "not-installed"
    return versions


def _safe_configuration(env):
    return {
        "profile": _allowed_value(
            env.get("PRICE_MIXER_ENV"), {"development", "production", "testing"}
        ),
        "log_level": _allowed_value(
            env.get("PRICE_MIXER_LOG_LEVEL"),
            {"critical", "error", "warning", "info", "debug"},
        ),
        "log_format": _allowed_value(
            env.get("PRICE_MIXER_LOG_FORMAT"), {"text", "json"}
        ),
        "workers": _safe_integer(env.get("PRICE_MIXER_WORKERS")),
        "threads": _safe_integer(env.get("PRICE_MIXER_THREADS")),
        "trust_proxy": _allowed_value(
            env.get("PRICE_MIXER_TRUST_PROXY"), {"0", "1", "false", "true"}
        ),
    }


def _allowed_value(value, allowed):
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else "unset-or-invalid"


def _safe_integer(value):
    normalized = str(value or "").strip()
    if not normalized.isdigit():
        return "unset-or-invalid"
    number = int(normalized)
    return number if 0 <= number <= 1024 else "unset-or-invalid"


def _declared_artifact_summary(root):
    result = {}
    for policy in ARTIFACT_POLICIES.values():
        if policy.sensitive:
            continue
        bucket = result.setdefault(
            policy.category,
            {"declared": 0, "present": 0, "total_bytes": 0},
        )
        bucket["declared"] += 1
    for name, policy in ARTIFACT_POLICIES.items():
        if policy.sensitive:
            continue
        path = root / name
        if not path.is_file():
            continue
        bucket = result[policy.category]
        bucket["present"] += 1
        bucket["total_bytes"] += _safe_file_size(path)
    return result


def _directory_summary(path):
    if not path.is_dir():
        return {"present": False, "directories": 0, "files": 0, "total_bytes": 0}
    directories = 0
    files = 0
    total_bytes = 0
    try:
        for item in path.rglob("*"):
            if item.is_dir():
                directories += 1
            elif item.is_file():
                files += 1
                total_bytes += _safe_file_size(item)
    except OSError:
        return {
            "present": True,
            "directories": directories,
            "files": files,
            "total_bytes": total_bytes,
            "scan_complete": False,
        }
    return {
        "present": True,
        "directories": directories,
        "files": files,
        "total_bytes": total_bytes,
        "scan_complete": True,
    }


def _safe_file_size(path):
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _database_summary(path):
    if not path.is_file():
        return {"present": False, "status": "missing"}
    result = {
        "present": True,
        "size_bytes": _safe_file_size(path),
    }
    connection = None
    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=ro",
            uri=True,
            timeout=2,
        )
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        result.update(
            {
                "status": "ok" if quick_check and quick_check[0] == "ok" else "invalid",
                "quick_check": "ok" if quick_check and quick_check[0] == "ok" else "failed",
                "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
                "table_count": connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
                ).fetchone()[0],
            }
        )
    except (OSError, sqlite3.Error) as exc:
        result.update({"status": "unavailable", "error_type": type(exc).__name__})
    finally:
        if connection is not None:
            connection.close()
    return result
