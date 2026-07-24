"""Scheduled backup orchestration with verification and collision refusal."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from price_mixer.logging_config import get_logger, log_context, new_job_id
from price_mixer.services.backup_restore import create_backup, verify_backup


LOGGER = get_logger("price_mixer.jobs.backup")


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
    return {
        "status": "ok",
        "job_id": job_id,
        "destination": str(destination),
        "files": len(manifest["files"]),
        "includes_secrets": manifest["includes_secrets"],
        "verification": verification,
    }
