import sqlite3
from pathlib import Path

import pytest

from price_mixer.runtime_paths import (
    RuntimePaths,
    ensure_runtime_directories,
    load_runtime_paths,
)
from price_mixer.services.backup_restore import create_backup
from price_mixer.services.runtime_migration import (
    build_runtime_migration_plan,
    copy_runtime_layout,
)


def _targets(tmp_path, project):
    runtime = tmp_path / "runtime"
    return RuntimePaths(
        project_root=project,
        state_dir=runtime / "state",
        data_dir=runtime / "data",
        cache_dir=runtime / "cache",
        uploads_dir=runtime / "uploads",
        logs_dir=runtime / "logs",
    )


def test_runtime_paths_keep_legacy_layout_without_environment(tmp_path):
    paths = load_runtime_paths({}, project_root=tmp_path)

    assert paths.state_dir == tmp_path.resolve()
    assert paths.data_dir == tmp_path.resolve()
    assert paths.cache_dir == tmp_path.resolve()
    assert paths.uploads_dir == (tmp_path / "uploads").resolve()
    assert paths.logs_dir == (tmp_path / "logs").resolve()


def test_runtime_paths_use_separated_environment_and_create_directories(tmp_path):
    root = tmp_path / "project"
    paths = load_runtime_paths(
        {
            "PRICE_MIXER_STATE_DIR": str(tmp_path / "state"),
            "PRICE_MIXER_DATA_DIR": str(tmp_path / "data"),
            "PRICE_MIXER_CACHE_DIR": str(tmp_path / "cache"),
            "PRICE_MIXER_UPLOAD_DIR": str(tmp_path / "uploads"),
            "PRICE_MIXER_LOG_DIR": str(tmp_path / "logs"),
        },
        project_root=root,
    )

    ensure_runtime_directories(paths)

    assert all(
        path.is_dir()
        for path in (
            paths.state_dir,
            paths.data_dir,
            paths.cache_dir,
            paths.uploads_dir,
            paths.logs_dir,
        )
    )


def test_runtime_migration_copies_and_verifies_without_removing_sources(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    state = project / "app_settings.json"
    state.write_text('{"ok": true}', encoding="utf-8")
    database = project / "onliner_products.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO sample DEFAULT VALUES")
    paths = _targets(tmp_path, project)

    plan = build_runtime_migration_plan(project, paths)
    result = copy_runtime_layout(project, paths, service_stopped=True)

    assert plan["status"] == "ok"
    assert result["status"] == "ok"
    assert result["source_files_removed"] is False
    assert state.is_file()
    assert database.is_file()
    assert (paths.state_dir / state.name).read_text(encoding="utf-8") == '{"ok": true}'
    with sqlite3.connect(paths.data_dir / database.name) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 1


def test_runtime_migration_requires_stopped_service_and_refuses_overwrite(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "app_settings.json").write_text("source", encoding="utf-8")
    paths = _targets(tmp_path, project)

    with pytest.raises(ValueError, match="service_stopped"):
        copy_runtime_layout(project, paths)

    paths.state_dir.mkdir(parents=True)
    target = paths.state_dir / "app_settings.json"
    target.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        copy_runtime_layout(project, paths, service_stopped=True)
    assert target.read_text(encoding="utf-8") == "keep"


def test_backup_reads_separated_state_and_data_paths(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    paths = _targets(tmp_path, project)
    ensure_runtime_directories(paths)
    (paths.state_dir / "app_settings.json").write_text("{}", encoding="utf-8")
    with sqlite3.connect(paths.data_dir / "onliner_products.db") as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")

    manifest = create_backup(
        project,
        tmp_path / "backup",
        runtime_paths=paths,
    )

    assert {item["relative_path"] for item in manifest["files"]} == {
        "app_settings.json",
        "onliner_products.db",
    }
