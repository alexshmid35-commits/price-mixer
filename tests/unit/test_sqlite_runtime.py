import sqlite3

import pytest

from price_mixer.services.sqlite_runtime import (
    BUSY_TIMEOUT_MS,
    connect_sqlite,
    maintain_runtime_databases,
    maintain_sqlite_database,
    reset_sqlite_runtime_state,
)


@pytest.fixture(autouse=True)
def reset_runtime_state():
    reset_sqlite_runtime_state()
    yield
    reset_sqlite_runtime_state()


def test_connect_sqlite_applies_shared_concurrency_policy(tmp_path):
    database = tmp_path / "data" / "catalog.db"

    with connect_sqlite(
        database,
        row_factory=sqlite3.Row,
        foreign_keys=True,
    ) as connection:
        connection.execute("CREATE TABLE items(id INTEGER PRIMARY KEY)")
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert isinstance(
            connection.execute("SELECT 1 AS value").fetchone(),
            sqlite3.Row,
        )


def test_maintenance_checkpoints_and_optimizes_existing_database(tmp_path):
    database = tmp_path / "catalog.db"
    with connect_sqlite(database) as connection:
        connection.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("CREATE INDEX idx_items_name ON items(name)")
        connection.execute("INSERT INTO items(name) VALUES ('SSD')")

    result = maintain_sqlite_database(database)

    assert result["status"] == "ok"
    assert result["checkpoint_mode"] == "passive"
    assert result["optimized"] is True
    assert result["busy"] == 0


def test_replaced_database_file_gets_wal_policy_again(tmp_path):
    database = tmp_path / "catalog.db"
    with connect_sqlite(database) as connection:
        connection.execute("CREATE TABLE old_items(id INTEGER PRIMARY KEY)")
    database.unlink()
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE new_items(id INTEGER PRIMARY KEY)")
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"

    with connect_sqlite(database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_runtime_maintenance_reports_missing_databases(tmp_path):
    existing = tmp_path / "jobs.db"
    with connect_sqlite(existing) as connection:
        connection.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY)")

    results = maintain_runtime_databases(
        tmp_path,
        names=("jobs.db", "missing.db"),
    )

    assert [item["status"] for item in results] == ["ok", "missing"]
