"""Verified Price Mixer backups and non-destructive restore planning."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from price_mixer.runtime_paths import get_runtime_paths, load_runtime_paths
from price_mixer.services.runtime_hygiene import (
    ARTIFACT_POLICIES,
    get_artifact_policy,
)


BACKUP_FORMAT = "price-mixer-backup-v1"
MANIFEST_FILENAME = "manifest.json"


def sha256_file(path, *, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(int(chunk_size))
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _existing_backup_sources(root, *, include_secrets, runtime_paths=None):
    root = Path(root).resolve()
    paths = runtime_paths or _runtime_paths_for_root(root)
    selected = []
    for name, policy in ARTIFACT_POLICIES.items():
        if not policy.backup_required or policy.category not in {
            "state",
            "data",
        }:
            continue
        base_dir = paths.state_dir if policy.category == "state" else paths.data_dir
        path = base_dir / name
        if path.is_file():
            selected.append((path, policy, name))

    if include_secrets:
        secret_candidates = list(root.glob(".env*"))
        secret_candidates.extend(root.glob("ai2025-*.json"))
        for path in secret_candidates:
            if not path.is_file():
                continue
            policy = get_artifact_policy(path, root)
            if policy is not None and policy.category == "secrets":
                selected.append((path, policy, path.name))

    unique = {}
    for path, policy, relative_name in selected:
        resolved = path.resolve()
        allowed_root = {
            "state": paths.state_dir,
            "data": paths.data_dir,
            "secrets": root,
        }[policy.category].resolve()
        if not resolved.is_relative_to(allowed_root):
            raise ValueError(f"Backup source escapes configured {policy.category} directory")
        unique[resolved] = (policy, relative_name)
    return [
        (path, *unique[path])
        for path in sorted(unique, key=lambda item: item.name)
    ]


def _runtime_paths_for_root(root):
    configured = get_runtime_paths()
    if configured.project_root == Path(root).resolve():
        return configured
    return load_runtime_paths({}, project_root=root)


def copy_sqlite_online(source, destination):
    source = Path(source).resolve()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"{source.as_uri()}?mode=ro"
    with closing(
        sqlite3.connect(
            source_uri,
            uri=True,
            timeout=30,
        )
    ) as source_db:
        with closing(
            sqlite3.connect(destination, timeout=30)
        ) as destination_db:
            source_db.backup(destination_db)
    result = sqlite_quick_check(destination)
    if result != "ok":
        raise RuntimeError(
            f"SQLite backup integrity check failed: {result}"
        )


def sqlite_quick_check(path):
    try:
        uri = f"{Path(path).resolve().as_uri()}?mode=ro"
        with closing(
            sqlite3.connect(uri, uri=True, timeout=30)
        ) as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
        return str((row or ["no result"])[0])
    except Exception as exc:
        return f"error: {type(exc).__name__}: {exc}"


def _copy_backup_source(source, destination, policy):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if policy.category == "data" and source.suffix.lower() in {
        ".db",
        ".sqlite",
    }:
        copy_sqlite_online(source, destination)
        return "sqlite"
    shutil.copy2(source, destination)
    if policy.category == "secrets":
        try:
            os.chmod(destination, 0o600)
        except OSError:
            pass
    return "file"


def _manifest_entry(relative_path, archive_path, policy, kind):
    archive_path = Path(archive_path)
    return {
        "relative_path": Path(relative_path).as_posix(),
        "archive_path": archive_path.as_posix(),
        "category": policy.category,
        "owner": policy.owner,
        "backup_required": bool(policy.backup_required),
        "sensitive": bool(policy.sensitive),
        "kind": kind,
    }


def create_backup(
    root,
    destination,
    *,
    include_secrets=False,
    created_at=None,
    runtime_paths=None,
):
    """Create a new verified backup without overwriting an existing path."""
    root = Path(root).resolve()
    destination = Path(destination).resolve()
    if not root.is_dir():
        raise ValueError("Project root does not exist")
    if destination.exists():
        raise FileExistsError(
            f"Backup destination already exists: {destination}"
        )
    if destination == root:
        raise ValueError("Backup destination cannot be the project root")

    sources = _existing_backup_sources(
        root,
        include_secrets=bool(include_secrets),
        runtime_paths=runtime_paths,
    )
    if not sources:
        raise ValueError("No durable backup sources were found")

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(destination.name + ".partial")
    if staging.exists():
        raise FileExistsError(
            f"Backup staging path already exists: {staging}"
        )
    staging.mkdir()

    entries = []
    try:
        for source, policy, relative_name in sources:
            relative_path = Path(relative_name)
            archive_path = Path(policy.category) / relative_path
            staged_path = staging / archive_path
            kind = _copy_backup_source(
                source,
                staged_path,
                policy,
            )
            entry = _manifest_entry(
                relative_path,
                archive_path,
                policy,
                kind,
            )
            entry["size"] = int(staged_path.stat().st_size)
            entry["sha256"] = sha256_file(staged_path)
            if kind == "sqlite":
                entry["sqlite_quick_check"] = "ok"
            entries.append(entry)

        manifest = {
            "format": BACKUP_FORMAT,
            "created_at": created_at
            or datetime.now(timezone.utc).isoformat(),
            "includes_secrets": any(
                entry["category"] == "secrets"
                for entry in entries
            ),
            "files": entries,
        }
        manifest_path = staging / MANIFEST_FILENAME
        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        verification = verify_backup(staging)
        if verification["status"] != "ok":
            raise RuntimeError(
                "Created backup failed verification: "
                + "; ".join(verification["errors"])
            )
        staging.replace(destination)
        return manifest
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def _load_manifest(backup_dir):
    manifest_path = Path(backup_dir) / MANIFEST_FILENAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(
            f"Cannot read backup manifest: {type(exc).__name__}"
        ) from exc
    if not isinstance(manifest, dict):
        raise ValueError("Backup manifest must be an object")
    if manifest.get("format") != BACKUP_FORMAT:
        raise ValueError("Unsupported backup manifest format")
    if not isinstance(manifest.get("files"), list):
        raise ValueError("Backup manifest files must be a list")
    return manifest


def _safe_archive_file(backup_dir, archive_path):
    backup_dir = Path(backup_dir).resolve()
    posix_path = PurePosixPath(str(archive_path or ""))
    if (
        not posix_path.parts
        or posix_path.is_absolute()
        or ".." in posix_path.parts
    ):
        raise ValueError("Unsafe archive path in manifest")
    resolved = (
        backup_dir / Path(*posix_path.parts)
    ).resolve()
    if not resolved.is_relative_to(backup_dir):
        raise ValueError("Archive path escapes backup directory")
    return resolved


def verify_backup(backup_dir):
    backup_dir = Path(backup_dir).resolve()
    errors = []
    checked = 0
    try:
        manifest = _load_manifest(backup_dir)
    except ValueError as exc:
        return {
            "status": "error",
            "errors": [str(exc)],
            "files_checked": 0,
        }

    for entry in manifest["files"]:
        if not isinstance(entry, dict):
            errors.append("Manifest contains a non-object file entry")
            continue
        try:
            path = _safe_archive_file(
                backup_dir, entry.get("archive_path")
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        label = str(entry.get("archive_path", "") or "")
        if not path.is_file():
            errors.append(f"Missing backup file: {label}")
            continue
        checked += 1
        actual_size = int(path.stat().st_size)
        if actual_size != int(entry.get("size", -1)):
            errors.append(f"Size mismatch: {label}")
            continue
        if sha256_file(path) != str(entry.get("sha256", "")):
            errors.append(f"Checksum mismatch: {label}")
            continue
        if entry.get("kind") == "sqlite":
            result = sqlite_quick_check(path)
            if result != "ok":
                errors.append(
                    f"SQLite integrity check failed: {label}: {result}"
                )

    return {
        "status": "ok" if not errors else "error",
        "errors": errors,
        "files_checked": checked,
    }


def _safe_restore_target(target_root, relative_path):
    target_root = Path(target_root).resolve()
    posix_path = PurePosixPath(str(relative_path or ""))
    if (
        not posix_path.parts
        or posix_path.is_absolute()
        or ".." in posix_path.parts
    ):
        raise ValueError("Unsafe restore path in manifest")
    if len(posix_path.parts) != 1:
        raise ValueError(
            "Restore target must be a declared project-root artifact"
        )
    target = (
        target_root / Path(*posix_path.parts)
    ).resolve()
    if not target.is_relative_to(target_root):
        raise ValueError("Restore path escapes target directory")
    return target


def build_restore_plan(
    backup_dir,
    target_root,
    *,
    include_secrets=False,
):
    """Return restore actions after verification; never modify target files."""
    verification = verify_backup(backup_dir)
    if verification["status"] != "ok":
        return {
            "status": "error",
            "errors": verification["errors"],
            "actions": [],
        }

    manifest = _load_manifest(backup_dir)
    actions = []
    errors = []
    seen_targets = set()
    for entry in manifest["files"]:
        category = str(entry.get("category", "") or "")
        if category == "secrets" and not include_secrets:
            continue
        try:
            relative_path = str(
                entry.get("relative_path", "") or ""
            )
            target = _safe_restore_target(
                target_root,
                relative_path,
            )
            policy = get_artifact_policy(target, Path(target_root).resolve())
            if (
                policy is None
                or policy.category != category
                or (
                    category != "secrets"
                    and not policy.backup_required
                )
            ):
                raise ValueError(
                    "Restore target is not a declared backup artifact: "
                    + relative_path
                )
            target_key = str(target).casefold()
            if target_key in seen_targets:
                raise ValueError(
                    "Duplicate restore target in manifest: "
                    + relative_path
                )
            seen_targets.add(target_key)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        actions.append(
            {
                "relative_path": relative_path,
                "category": category,
                "sensitive": bool(entry.get("sensitive", False)),
                "action": "replace" if target.exists() else "create",
            }
        )
    return {
        "status": "ok" if not errors else "error",
        "errors": errors,
        "actions": actions if not errors else [],
    }
