import json
import runpy
import sqlite3
from pathlib import Path

import pytest

from price_mixer.services.backup_restore import (
    BACKUP_FORMAT,
    build_restore_plan,
    create_backup,
    verify_backup,
)


ROOT = Path(__file__).resolve().parents[2]


def _project_fixture(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "app_settings.json").write_text(
        '{"ui": {"show": true}}',
        encoding="utf-8",
    )
    (project / "manual_id_bindings.json").write_text(
        '{"product": {"id": "123"}}',
        encoding="utf-8",
    )
    (project / "onliner_cache.json").write_text(
        '{"rebuildable": true}',
        encoding="utf-8",
    )
    (project / ".env").write_text(
        "ADMIN_PASSWORD=not-a-real-secret",
        encoding="utf-8",
    )
    (project / "ai2025-test.json").write_text(
        '{"type": "service_account"}',
        encoding="utf-8",
    )
    database = project / "onliner_products.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT)"
        )
        connection.execute(
            "INSERT INTO products(name) VALUES (?)",
            ("SSD Test",),
        )
        connection.commit()
    return project


def test_create_backup_copies_state_and_consistent_sqlite_not_cache_or_secrets(
    tmp_path,
):
    project = _project_fixture(tmp_path)
    backup = tmp_path / "backup"

    manifest = create_backup(
        project,
        backup,
        created_at="2026-07-23T00:00:00+00:00",
    )

    assert manifest["format"] == BACKUP_FORMAT
    assert manifest["created_at"] == "2026-07-23T00:00:00+00:00"
    assert manifest["includes_secrets"] is False
    relative_paths = {
        entry["relative_path"] for entry in manifest["files"]
    }
    assert relative_paths == {
        "app_settings.json",
        "manual_id_bindings.json",
        "onliner_products.db",
    }
    assert not (backup / "cache" / "onliner_cache.json").exists()
    assert not (backup / "secrets" / ".env").exists()
    assert verify_backup(backup) == {
        "status": "ok",
        "errors": [],
        "files_checked": 3,
    }
    with sqlite3.connect(
        backup / "data" / "onliner_products.db"
    ) as connection:
        assert connection.execute(
            "SELECT name FROM products"
        ).fetchone() == ("SSD Test",)


def test_create_backup_keeps_explicit_secrets_in_separate_directory(
    tmp_path,
):
    project = _project_fixture(tmp_path)
    backup = tmp_path / "backup-with-secrets"

    manifest = create_backup(
        project,
        backup,
        include_secrets=True,
    )

    assert manifest["includes_secrets"] is True
    assert (backup / "secrets" / ".env").is_file()
    assert (
        backup / "secrets" / "ai2025-test.json"
    ).is_file()
    assert verify_backup(backup)["status"] == "ok"


def test_verify_backup_detects_checksum_tampering(tmp_path):
    project = _project_fixture(tmp_path)
    backup = tmp_path / "backup"
    create_backup(project, backup)
    state_file = backup / "state" / "app_settings.json"
    state_file.write_text("tampered", encoding="utf-8")

    result = verify_backup(backup)

    assert result["status"] == "error"
    assert result["errors"] == [
        "Size mismatch: state/app_settings.json"
    ]


def test_restore_plan_is_verified_and_never_changes_target(tmp_path):
    project = _project_fixture(tmp_path)
    backup = tmp_path / "backup"
    create_backup(project, backup, include_secrets=True)
    target = tmp_path / "restore-target"
    target.mkdir()
    current_settings = target / "app_settings.json"
    current_settings.write_text("current", encoding="utf-8")

    result = build_restore_plan(backup, target)

    assert result["status"] == "ok"
    actions = {
        item["relative_path"]: item["action"]
        for item in result["actions"]
    }
    assert actions["app_settings.json"] == "replace"
    assert actions["manual_id_bindings.json"] == "create"
    assert actions["onliner_products.db"] == "create"
    assert ".env" not in actions
    assert current_settings.read_text(encoding="utf-8") == "current"
    assert not (target / "manual_id_bindings.json").exists()


def test_restore_plan_rejects_manifest_path_traversal(tmp_path):
    project = _project_fixture(tmp_path)
    backup = tmp_path / "backup"
    create_backup(project, backup)
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["relative_path"] = "../outside.json"
    manifest_path.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    result = build_restore_plan(
        backup,
        tmp_path / "restore-target",
    )

    assert result == {
        "status": "error",
        "errors": ["Unsafe restore path in manifest"],
        "actions": [],
    }
    assert not (tmp_path / "outside.json").exists()


def test_restore_plan_rejects_undeclared_target(tmp_path):
    project = _project_fixture(tmp_path)
    backup = tmp_path / "backup"
    create_backup(project, backup)
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["relative_path"] = "app.py"
    manifest_path.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    result = build_restore_plan(
        backup,
        tmp_path / "restore-target",
    )

    assert result == {
        "status": "error",
        "errors": [
            "Restore target is not a declared backup artifact: app.py"
        ],
        "actions": [],
    }


def test_create_backup_refuses_existing_destination(tmp_path):
    project = _project_fixture(tmp_path)
    backup = tmp_path / "backup"
    backup.mkdir()

    with pytest.raises(FileExistsError):
        create_backup(project, backup)


def test_backup_cli_verify_reports_success(tmp_path, capsys):
    project = _project_fixture(tmp_path)
    backup = tmp_path / "backup"
    create_backup(project, backup)
    namespace = runpy.run_path(
        str(ROOT / "deploy" / "backup_restore.py")
    )

    exit_code = namespace["main"](["verify", str(backup)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["status"] == "ok"
    assert output["files_checked"] == 3


def test_backup_cli_returns_structured_error(tmp_path, capsys):
    namespace = runpy.run_path(
        str(ROOT / "deploy" / "backup_restore.py")
    )
    existing = tmp_path / "existing"
    existing.mkdir()

    exit_code = namespace["main"](
        [
            "create",
            str(existing),
            "--root",
            str(tmp_path),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output["status"] == "error"
    assert output["errors"][0].startswith("FileExistsError:")
