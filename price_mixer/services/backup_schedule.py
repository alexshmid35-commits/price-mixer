"""Scheduled backup orchestration with verification and collision refusal."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import shutil

from price_mixer.logging_config import get_logger, log_context, new_job_id
from price_mixer.services.backup_restore import create_backup, verify_backup


LOGGER = get_logger("price_mixer.jobs.backup")
SCHEDULED_BACKUP_PATTERN = re.compile(
    r"^price-mixer-(\d{8}T\d{6}Z)$"
)


def scheduled_backup_name(now=None):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    return f"price-mixer-{current.strftime('%Y%m%dT%H%M%SZ')}"


def create_scheduled_backup(
    project_root,
    backup_root,
    *,
    now=None,
    include_secrets=False,
    keep_daily=7,
    keep_weekly=4,
):
    """Create and independently verify one timestamped scheduled backup."""
    project_root = Path(project_root).resolve()
    backup_root = Path(backup_root).resolve()
    if backup_root == project_root or backup_root.is_relative_to(project_root):
        raise ValueError("scheduled backup directory must be outside the project root")
    destination = backup_root / scheduled_backup_name(now)
    job_id = new_job_id()
    with log_context(job_id=job_id):
        LOGGER.info("scheduled backup started")
        manifest = create_backup(
            project_root,
            destination,
            include_secrets=include_secrets,
            created_at=(
                (now or datetime.now(timezone.utc))
                .astimezone(timezone.utc)
                .isoformat()
            ),
        )
        verification = verify_backup(destination)
        if verification["status"] != "ok":
            raise RuntimeError("scheduled backup verification failed")
        LOGGER.info(
            "scheduled backup completed files=%s secrets=%s",
            len(manifest["files"]),
            manifest["includes_secrets"],
        )
        retention = prune_scheduled_backups(
            backup_root,
            keep_daily=keep_daily,
            keep_weekly=keep_weekly,
            protected_paths={destination},
        )
    return {
        "status": "ok",
        "job_id": job_id,
        "destination": str(destination),
        "files": len(manifest["files"]),
        "includes_secrets": manifest["includes_secrets"],
        "verification": verification,
        "retention": retention,
    }


def prune_scheduled_backups(
    backup_root,
    *,
    keep_daily=7,
    keep_weekly=4,
    protected_paths=None,
    dry_run=False,
):
    """Remove only verified scheduled backups outside the retention window."""
    root = Path(backup_root).resolve()
    keep_daily = max(1, int(keep_daily))
    keep_weekly = max(0, int(keep_weekly))
    protected = {
        Path(path).resolve()
        for path in (protected_paths or set())
    }
    verified = []
    skipped = []
    if not root.exists():
        return {
            "kept": 0,
            "removed": 0,
            "removed_paths": [],
            "skipped_unverified": [],
        }

    for candidate in root.iterdir():
        timestamp = _scheduled_backup_timestamp(candidate)
        if timestamp is None:
            continue
        verification = verify_backup(candidate)
        if verification.get("status") != "ok":
            skipped.append(candidate.name)
            continue
        verified.append((timestamp, candidate.resolve()))
    verified.sort(key=lambda item: item[0], reverse=True)

    keep = set(protected)
    daily_dates = set()
    for timestamp, path in verified:
        day = timestamp.date()
        if day in daily_dates:
            continue
        if len(daily_dates) >= keep_daily:
            break
        daily_dates.add(day)
        keep.add(path)

    weekly_keys = set()
    for timestamp, path in verified:
        if path in keep:
            continue
        iso_year, iso_week, _ = timestamp.isocalendar()
        week = (iso_year, iso_week)
        if week in weekly_keys:
            continue
        if len(weekly_keys) >= keep_weekly:
            break
        weekly_keys.add(week)
        keep.add(path)

    removed = []
    for _timestamp, path in verified:
        if path in keep:
            continue
        removed.append(path.name)
        if not dry_run:
            shutil.rmtree(path)

    return {
        "kept": len(verified) - len(removed),
        "removed": len(removed),
        "removed_paths": removed,
        "skipped_unverified": sorted(skipped),
    }


def _scheduled_backup_timestamp(path):
    candidate = Path(path)
    if not candidate.is_dir():
        return None
    match = SCHEDULED_BACKUP_PATTERN.fullmatch(candidate.name)
    if match is None:
        return None
    try:
        return datetime.strptime(
            match.group(1),
            "%Y%m%dT%H%M%SZ",
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
