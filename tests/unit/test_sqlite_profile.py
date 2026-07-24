import importlib.util
import sqlite3
import time
from pathlib import Path

from price_mixer.services.session_products import SessionProductStore

ROOT = Path(__file__).resolve().parents[2]


def _load_script(name):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_sqlite_profile_reports_indexed_session_and_catalog_plans(tmp_path):
    profiler = _load_script("profile_sqlite")
    session_db = tmp_path / "session.db"
    store = SessionProductStore(session_db, mode="canonical")
    store.replace_rows(
        tmp_path / "session",
        [
            ["", "Lenovo notebook", 10, "IVEN", "12", "2", 11, 12, 0, "Ноутбук"],
            ["42", "Samsung SSD", 20, "Tradex", "12", "2", 22, 24, 1, "SSD"],
        ],
        source_revision="test",
    )
    catalog_db = tmp_path / "catalog.db"
    with sqlite3.connect(catalog_db) as connection:
        connection.executescript(
            """
            CREATE TABLE onliner_catalog(
                onliner_id TEXT PRIMARY KEY,
                name TEXT,
                url TEXT
            );
            CREATE TABLE name_index(
                onliner_id TEXT,
                raw_name TEXT
            );
            CREATE VIRTUAL TABLE name_index_fts USING fts5(
                onliner_id UNINDEXED,
                raw_name
            );
            INSERT INTO onliner_catalog VALUES ('42','Samsung SSD','https://example/42');
            INSERT INTO name_index VALUES ('42','Samsung SSD');
            INSERT INTO name_index_fts VALUES ('42','Samsung SSD');
            """
        )

    report = profiler.build_report(
        catalog_db=catalog_db,
        session_db=session_db,
    )

    assert [item["status"] for item in report["databases"]] == ["ok", "ok"]
    session = report["databases"][1]
    assert session["session"]["row_count"] == 2
    assert session["plans"]["without_id_categories"]["temporary_btree"] is False


def test_matching_worker_benchmark_compares_requested_concurrency():
    benchmark = _load_script("benchmark_matching_workers")

    def lookup(name):
        time.sleep(0.001)
        return [{"name": name}]

    results, recommended = benchmark.benchmark_workers(
        ["a", "b", "c", "d"],
        (1, 2, 4),
        lookup,
        repeats=1,
    )

    assert [item["workers"] for item in results] == [1, 2, 4]
    assert all(item["candidate_count"] == 4 for item in results)
    assert recommended in {1, 2, 4}
