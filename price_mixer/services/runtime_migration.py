"""Non-destructive migration from the legacy project-root runtime layout."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from price_mixer.runtime_paths import RuntimePaths
from price_mixer.services.backup_restore import (
    copy_sqlite_online,
    sha256_file,
    sqlite_quick_check,
)
from price_mixer.services.runtime_hygiene import ARTIFACT_POLICIES


def build_runtime_migration_plan(project_root, target_paths):
    """Describe durable copies without creating or changing any path."""
    root = Path(project_root).resolve()
    paths = _validate_targets(root, target_paths)
    actions = []
    for name, policy in sorted(ARTIFACT_POLICIES.items()):
        if policy.category not in {"state", "data"}:
            continue
        source = root / name
        target_dir = paths.state_dir if policy.category == "state" else paths.data_dir
        target = target_dir / name
        action = "copy"
        if not source.is_file():
            action = "skip_missing"
        elif target.exists():
            action = "blocked_exists"
        actions.append(
            {
                "name": name,
                "category": policy.category,
                "source": str(source),
                "target": str(target),
                "action": action,
            }
        )
    return {
        "status": "blocked"
        if any(item["action"] == "blocked_exists" for item in actions)
        else "ok",
        "source_files_removed": False,
        "actions": actions,
    }


def copy_runtime_layout(project_root, target_paths, *, service_stopped=False):
    """Copy durable runtime files after an explicit stopped-service assertion."""
    if not service_stopped:
        raise ValueError("service_stopped confirmation is required")
    plan = build_runtime_migration_plan(project_root, target_paths)
    if plan["status"] != "ok":
        raise FileExistsError("one or more runtime migration targets already exist")
    copy_actions = [item for item in plan["actions"] if item["action"] == "copy"]
    if not copy_actions:
        raise ValueError("no legacy durable runtime files were found")

    copied = []
    temporary_paths = []
    try:
        for item in copy_actions:
            source = Path(item["source"])
            target = Path(item["target"])
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(
                f".{target.name}.{uuid.uuid4().hex}.partial"
            )
            temporary_paths.append(temporary)
            if item["category"] == "data" and source.suffix.lower() in {
                ".db",
                ".sqlite",
            }:
                copy_sqlite_online(source, temporary)
                if sqlite_quick_check(temporary) != "ok":
                    raise RuntimeError("migrated SQLite verification failed")
            else:
                shutil.copy2(source, temporary)
                if sha256_file(source) != sha256_file(temporary):
                    raise RuntimeError("migrated file checksum verification failed")
            os.link(temporary, target)
            temporary.unlink()
            copied.append(target)
    except Exception:
        for target in copied:
            target.unlink(missing_ok=True)
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)
        raise
    return {
        "status": "ok",
        "copied": len(copied),
        "source_files_removed": False,
        "actions": plan["actions"],
    }


def _validate_targets(project_root, paths):
    if not isinstance(paths, RuntimePaths):
        raise TypeError("target_paths must be RuntimePaths")
    runtime_dirs = {
        paths.state_dir.resolve(),
        paths.data_dir.resolve(),
        paths.cache_dir.resolve(),
        paths.uploads_dir.resolve(),
        paths.logs_dir.resolve(),
    }
    if len(runtime_dirs) != 5:
        raise ValueError("runtime directories must be distinct")
    if any(
        path == project_root or path.is_relative_to(project_root)
        for path in runtime_dirs
    ):
        raise ValueError("runtime directories must be outside the project root")
    return paths
