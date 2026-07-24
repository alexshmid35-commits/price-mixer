import json
import runpy
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from price_mixer.services.backup_schedule import (
    create_scheduled_backup,
    prune_scheduled_backups,
    scheduled_backup_name,
)


ROOT = Path(__file__).resolve().parents[2]


def _project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "app_settings.json").write_text("{}", encoding="utf-8")
    with sqlite3.connect(root / "onliner_products.db") as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
    return root


def test_scheduled_backup_creates_timestamped_verified_directory(tmp_path):
    project = _project(tmp_path)
    backup_root = tmp_path / "external-backups"
    now = datetime(2026, 7, 24, 1, 2, 3, tzinfo=timezone.utc)

    result = create_scheduled_backup(project, backup_root, now=now)

    assert scheduled_backup_name(now) == "price-mixer-20260724T010203Z"
    assert result["status"] == "ok"
    assert result["includes_secrets"] is False
    assert result["verification"]["status"] == "ok"
    assert (
        backup_root
        / "price-mixer-20260724T010203Z"
        / "manifest.json"
    ).is_file()


def test_scheduled_backup_refuses_project_internal_destination(tmp_path):
    project = _project(tmp_path)

    with pytest.raises(ValueError, match="outside"):
        create_scheduled_backup(project, project / "backups")


def test_scheduled_backup_refuses_same_timestamp_collision(tmp_path):
    project = _project(tmp_path)
    backup_root = tmp_path / "external-backups"
    now = datetime(2026, 7, 24, 1, 2, 3, tzinfo=timezone.utc)
    create_scheduled_backup(project, backup_root, now=now)

    with pytest.raises(FileExistsError):
        create_scheduled_backup(project, backup_root, now=now)


def test_scheduled_backup_retention_keeps_daily_and_weekly_points(tmp_path):
    project = _project(tmp_path)
    backup_root = tmp_path / "external-backups"
    start = datetime(2026, 7, 1, 1, 2, 3, tzinfo=timezone.utc)
    for offset in range(12):
        create_scheduled_backup(
            project,
            backup_root,
            now=start + timedelta(days=offset),
            keep_daily=100,
            keep_weekly=0,
        )

    result = prune_scheduled_backups(
        backup_root,
        keep_daily=3,
        keep_weekly=2,
    )

    assert result["kept"] == 5
    assert result["removed"] == 7
    assert len(list(backup_root.glob("price-mixer-*"))) == 5


def test_scheduled_backup_retention_never_removes_unverified_directory(tmp_path):
    backup_root = tmp_path / "external-backups"
    invalid = backup_root / "price-mixer-20260701T010203Z"
    invalid.mkdir(parents=True)
    (invalid / "broken.txt").write_text("broken", encoding="utf-8")

    result = prune_scheduled_backups(
        backup_root,
        keep_daily=1,
        keep_weekly=0,
    )

    assert invalid.is_dir()
    assert result["removed"] == 0
    assert result["skipped_unverified"] == [invalid.name]


def test_scheduled_backup_cli_returns_structured_error(tmp_path, capsys):
    namespace = runpy.run_path(
        str(ROOT / "deploy" / "scheduled_backup.py")
    )
    project = _project(tmp_path)

    exit_code = namespace["main"](
        [
            "--root",
            str(project),
            "--destination-root",
            str(project / "backups"),
        ]
    )

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_backup_systemd_timer_is_persistent_and_hardened():
    service = (
        ROOT / "deploy" / "price-mixer-backup.service"
    ).read_text(encoding="utf-8")
    timer = (
        ROOT / "deploy" / "price-mixer-backup.timer"
    ).read_text(encoding="utf-8")

    assert "deploy/scheduled_backup.py" in service
    assert "ReadOnlyPaths=/opt/price-mixer/current" in service
    assert "ReadWritePaths=/srv/price-mixer-backups" in service
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=15m" in timer
