"""Unit tests for local Onliner database service."""

from pathlib import Path
import csv

import pandas as pd

from price_mixer.services import onliner_db


def test_fts_search_tokens_split_hyphenated_article_like_sqlite_fts():
    assert onliner_db._fts_search_tokens("ID-Cooling IS-47-XT") == ["id", "cooling", "is", "47", "xt"]


def test_fts_index_rebuilds_stale_rows_and_tracks_new_inserts(monkeypatch, tmp_path):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    with onliner_db.db_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO onliner_catalog(onliner_id, name, url) VALUES (?, ?, ?)",
            ("1", "Ноутбук Lenovo First", ""),
        )
        conn.execute(
            "INSERT INTO name_index(name_key, onliner_id, raw_name) VALUES (?, ?, ?)",
            ("ноутбук lenovo first", "1", "Ноутбук Lenovo First"),
        )
        onliner_db._ensure_search_fts(conn, force=True)

    with onliner_db.db_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO onliner_catalog(onliner_id, name, url) VALUES (?, ?, ?)",
            ("2", "Ноутбук Lenovo 83JG007LRK", ""),
        )
        conn.execute(
            "INSERT INTO name_index(name_key, onliner_id, raw_name) VALUES (?, ?, ?)",
            ("ноутбук lenovo 83jg007lrk", "2", "Ноутбук Lenovo 83JG007LRK"),
        )

    with onliner_db.db_connection(db_path) as conn:
        onliner_db._ensure_search_fts(conn)
        counts = (
            conn.execute("SELECT COUNT(*) FROM name_index").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM name_index_fts").fetchone()[0],
        )
        result = conn.execute(
            "SELECT onliner_id FROM name_index_fts WHERE name_index_fts MATCH ?",
            ('"83jg007lrk"*',),
        ).fetchone()

    assert counts == (2, 2)
    assert result[0] == "2"


def test_best_candidate_match_uses_url_only_when_it_improves_the_name_match():
    def calc(_local, candidate):
        if "good-code" in candidate:
            return {"score": 0.99, "match": True, "reason": "article_like"}
        if "bad-slug" in candidate:
            return {"score": 0.2, "match": False, "reason": "article_conflict"}
        return {"score": 0.8, "match": True, "reason": "tokens"}

    improved = onliner_db._best_candidate_match(calc, "Local", "Candidate", "https://x/good-code")
    preserved = onliner_db._best_candidate_match(calc, "Local", "Candidate", "https://x/bad-slug")

    assert improved["score"] == 0.99
    assert preserved["score"] == 0.8


def _use_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "onliner_products.db"
    monkeypatch.setattr(onliner_db, "ONLINER_DB_FILE", db_path)
    onliner_db.catalog_import_status.update({
        "running": False,
        "total": 0,
        "done": 0,
        "inserted": 0,
        "skipped": 0,
        "message": "",
        "percent": 0,
        "finished_at": None,
    })
    onliner_db.init_onliner_db()
    return db_path


def _name_key(value):
    return str(value or "").strip().lower().replace(" ", "")


def test_populate_stats_and_search_payload(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    df = pd.DataFrame([
        {
            "Название": "Kingston NV2 1TB",
            "OnlinerID": "12345",
            "Ссылка": "https://catalog.onliner.by/ssd/kingston/nv21tb",
            "Поставщик": "IVEN",
        },
        {
            "Название": "TGPC Action 81872 A-X",
            "OnlinerID": "99999",
            "Ссылка": "https://catalog.onliner.by/desktop/tgpc/action",
            "Поставщик": "TGPC",
        },
    ])

    products, names = onliner_db.populate_from_df(
        df,
        "price_load",
        normalize_name_key=_name_key,
        skip_suppliers=["TGPC"],
    )

    assert (products, names) == (1, 1)
    assert onliner_db.stats_payload()["total_products"] == 1
    assert onliner_db.search_payload("kingston")["items"][0]["id"] == "12345"


def test_upsert_and_find_exact(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)

    onliner_db.upsert_product(
        "777",
        "AMD Ryzen 5 5600",
        "https://catalog.onliner.by/cpu/amd/5600",
        normalize_name_key=_name_key,
        source="manual",
    )

    product = onliner_db.get_product_by_id("777")
    exact = onliner_db.find_exact_id_for_name("AMD Ryzen 5 5600", normalize_name_key=_name_key)

    assert product["name"] == "AMD Ryzen 5 5600"
    assert product["source"] == "manual"
    assert exact["id"] == "777"
    assert exact["source"] == "db_exact"


def test_update_categories_replaces_name_only_for_catalog_api_result(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    onliner_db.upsert_product(
        "777",
        "Old catalog name",
        "https://catalog.onliner.by/old",
        normalize_name_key=_name_key,
        source="catalog_import",
    )

    assert onliner_db.update_categories([{
        "onliner_id": "777",
        "name": "Ugly supplier price-list name",
        "category": "SSD",
        "source": "parent_category_fallback",
    }]) == 1
    assert onliner_db.get_product_by_id("777")["name"] == "Old catalog name"

    assert onliner_db.update_categories([{
        "onliner_id": "777",
        "name": "Canonical Onliner name",
        "url": "https://catalog.onliner.by/ssd/canonical",
        "category": "SSD",
        "source": "catalog_api_id",
    }]) == 1
    product = onliner_db.get_product_by_id("777")
    assert product["name"] == "Canonical Onliner name"
    assert product["url"] == "https://catalog.onliner.by/ssd/canonical"


def test_update_categories_normalizes_onliner_slug_categories(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)

    assert onliner_db.update_categories([{
        "onliner_id": "888",
        "name": "Bosch drill bit",
        "category": "Drillbits",
        "source": "catalog_api_id",
    }]) == 1

    assert onliner_db.get_categories_by_ids(["888"]) == {"888": "Сверла и буры"}


def test_get_distinct_categories_normalizes_existing_slug_categories(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)

    onliner_db.update_categories([
        {"onliner_id": "888", "name": "Drill", "category": "Drillbits", "source": "catalog_api_id"},
        {"onliner_id": "999", "name": "Book", "category": "Электронные книги", "source": "catalog_api_id"},
    ])

    assert onliner_db.get_distinct_categories() == ["Сверла и буры", "Электронные книги"]


def test_catalog_import_worker_imports_new_rows(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    csv_path = tmp_path / "catalog.csv"
    csv_path.write_text(
        "Category,B,Model,D,OnlinerID,F,G,FullName\n"
        "SSD,,NV2 1TB,,12345,,,Kingston NV2 1TB\n"
        "CPU,,Ryzen 5 5600,,777,,,AMD Ryzen 5 5600\n",
        encoding="utf-8",
    )

    onliner_db.catalog_import_worker(
        str(csv_path),
        ".csv",
        normalize_name_key=_name_key,
        cleanup_file=False,
    )

    status = onliner_db.import_status_payload()
    assert status["running"] is False
    assert status["inserted"] == 2
    assert status["skipped"] == 0
    assert status["percent"] == 100
    assert "пропущено" in status["message"]
    assert onliner_db.stats_payload()["total_products"] == 2


def test_import_summary_counts_actual_changes_and_survives_failure(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    path = tmp_path / 'catalog.csv'
    header = 'Category,B,Model,D,OnlinerID,F,G,FullName\n'
    path.write_text(header + 'SSD,,A,,1,,,Drive A\nSSD,,B,,2,,,Drive B\n')
    def run():
        return onliner_db.catalog_import_worker(str(path), '.csv', normalize_name_key=_name_key, cleanup_file=False)
    assert run() is True
    assert onliner_db.stats_payload()['last_import']['inserted'] == 2
    assert onliner_db.stats_payload()['last_import']['updated'] == 0
    path.write_text(header + 'SSD,,A,,1,,,Drive A renamed\nSSD,,B,,2,,,Drive B\nSSD,,C,,3,,,Drive C\n')
    assert run() is True
    last = onliner_db.stats_payload()['last_import']
    assert last['inserted'] == 1 and last['updated'] == 1
    # Source and timestamp updates alone are not product changes.
    assert run() is True
    last = onliner_db.stats_payload()['last_import']
    assert last['inserted'] == 0 and last['updated'] == 0
    assert last['finished_at'] > 0
    path.unlink()
    assert run() is False
    assert onliner_db.stats_payload()['last_import'] == last


def test_import_summary_counts_category_changes_once_per_product(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    path = tmp_path / 'catalog.csv'
    path.write_text('Category,B,Model,D,OnlinerID,F,G,FullName\nSSD,,A,,1,,,A\n')
    onliner_db.catalog_import_worker(str(path), '.csv', normalize_name_key=_name_key, cleanup_file=False)
    path.write_text('Category,B,Model,D,OnlinerID,F,G,FullName\nCPU,,A,,1,,,A\nCPU,,A,,1,,,A\n')
    onliner_db.catalog_import_worker(str(path), '.csv', normalize_name_key=_name_key, cleanup_file=False)
    assert onliner_db.stats_payload()['last_import']['updated'] == 1


def test_catalog_import_worker_reports_skipped_rows(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    csv_path = tmp_path / "catalog.csv"
    csv_path.write_text(
        "Category,B,Model,D,OnlinerID,F,G,FullName\n"
        "SSD,,NV2 1TB,,12345,,,Kingston NV2 1TB\n"
        "CPU,,No ID,,,,,AMD Ryzen without ID\n",
        encoding="utf-8",
    )

    onliner_db.catalog_import_worker(
        str(csv_path),
        ".csv",
        normalize_name_key=_name_key,
        cleanup_file=False,
    )

    status = onliner_db.import_status_payload()
    assert status["inserted"] == 1
    assert status["skipped"] == 1
    assert "1 пропущено" in status["message"]


def test_import_csv_payload_validates_extension(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)

    class FileStub:
        filename = "catalog.txt"

    body, status = onliner_db.import_csv_payload(
        FileStub(),
        normalize_name_key=_name_key,
        start_thread=lambda target: target(),
    )

    assert status == 400
    assert body["message"] == "Поддерживаются только CSV и XLSX"


def test_catalog_import_accepts_projected_columns_without_losing_first_product(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    path = tmp_path / "core.csv"
    path.write_text(
        '"Category","Model","onliner_id","Specs"\n'
        '"Процессоры","AMD Ryzen 7 7800X3D","3808268","Процессор AMD Ryzen 7 7800X3D"\n'
        '"SSD","NV2 1TB","12345","Kingston NV2 1TB"\n', encoding="utf-8",
    )
    onliner_db.catalog_import_worker(str(path), ".csv", normalize_name_key=_name_key, cleanup_file=False)
    status = onliner_db.import_status_payload()
    assert status["inserted"] == 2
    assert status["done"] == 2
    assert status["percent"] == 100
    assert onliner_db.get_product_by_id("3808268")["name"] == "Процессор AMD Ryzen 7 7800X3D"
    assert onliner_db.get_product_by_id("12345")["category"] == "SSD"


def test_catalog_csv_accepts_large_ignored_field_without_field_limit_failure(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    path = tmp_path / "large.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Category", "B", "Model", "D", "OnlinerID", "URL", "image_url", "FullName"])
        writer.writerow(["SSD", "", "NV2 1TB", "", "12345", "", "x" * 150_000, "Kingston NV2 1TB"])
    old_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(131072)
        onliner_db.catalog_import_worker(str(path), ".csv", normalize_name_key=_name_key, cleanup_file=False)
        assert onliner_db.import_status_payload()["inserted"] == 1
        assert onliner_db.get_product_by_id("12345")["name"] == "Kingston NV2 1TB"
    finally:
        csv.field_size_limit(old_limit)


def test_projected_import_updates_existing_category_and_preserves_url(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    svc = onliner_db
    svc.upsert_product("12345", "Old name", "https://catalog.onliner.by/ssd/kingston/nv2", normalize_name_key=_name_key)
    path = tmp_path / "core.csv"
    path.write_text(
        'Category,Model,onliner_id,Specs\nSSD,NV2,12345,Kingston NV2\nSSD,NV3,67890,\n', encoding="utf-8",
    )
    normalized = []
    normalize = svc.normalize_catalog_category_name
    monkeypatch.setattr(svc, "normalize_catalog_category_name", lambda name: normalized.append(name) or normalize(name))
    svc.catalog_import_worker(str(path), ".csv", normalize_name_key=_name_key, cleanup_file=False)
    assert normalized == ["SSD"]
    assert svc.import_status_payload()["inserted"] == 1
    assert svc.import_status_payload()["existing"] == 1
    product = svc.get_product_by_id("12345")
    assert product["name"] == "Kingston NV2"
    assert product["url"] == "https://catalog.onliner.by/ssd/kingston/nv2"
    assert svc.get_product_by_id("67890")["name"] == "SSD NV3"
