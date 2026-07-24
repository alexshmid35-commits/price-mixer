import json
import runpy
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from price_mixer.services.backup_schedule import (
    create_scheduled_backup,
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
