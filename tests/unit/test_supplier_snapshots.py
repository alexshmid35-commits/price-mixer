"""Unit tests for supplier snapshot and API fetch history helpers."""

import pandas as pd

from price_mixer.services import supplier_snapshots
from price_mixer.services.supplier_snapshots import (
    append_api_fetch_history,
    build_supplier_snapshot,
    compare_supplier_snapshot,
    get_api_fetch_history,
    latest_supplier_snapshot,
    load_session_supplier_diff,
    save_session_supplier_diff,
    upsert_supplier_snapshot,
)


def test_build_supplier_snapshot_filters_supplier_and_uses_category_getter(monkeypatch):
    monkeypatch.setattr(supplier_snapshots.time, "time", lambda: 123)
    df = pd.DataFrame([
        {"Поставщик": "BN", "Название": "SSD 1TB", "Цена": "100.126", "OnlinerID": "42.0"},
        {"Поставщик": "TGPC", "Название": "CPU 5600", "Цена": "200", "OnlinerID": ""},
    ])

    snapshot = build_supplier_snapshot(df, "BN", category_getter=lambda row: f"cat:{row['Поставщик']}")

    assert snapshot == {
        "updated_at": 123,
        "items": {
            "oid:42": {
                "name": "SSD 1TB",
                "price": 100.13,
                "onliner_id": "42",
                "category": "cat:BN",
                "has_id": True,
            },
        },
    }


def test_compare_supplier_snapshot_reports_new_removed_price_changed_and_no_id():
    previous = {
        "updated_at": 10,
        "items": {
            "oid:1": {"name": "Old price", "price": 100, "onliner_id": "1", "category": "SSD"},
            "oid:2": {"name": "Removed", "price": 50, "onliner_id": "2", "category": "CPU"},
        },
    }
    current = {
        "updated_at": 20,
        "items": {
            "oid:1": {"name": "Old price", "price": 120, "onliner_id": "1", "category": "SSD"},
            "name:new": {"name": "New without ID", "price": 30, "onliner_id": "", "category": "RAM"},
        },
    }

    diff = compare_supplier_snapshot(previous, current)

    assert diff["available"] is True
    assert diff["new_count"] == 1
    assert diff["removed_count"] == 1
    assert diff["price_changed_count"] == 1
    assert diff["new_without_id_count"] == 1
    assert diff["filters"]["new_without_id_names"] == ["New without ID"]


def test_latest_and_upsert_supplier_snapshot_keep_session_shape():
    old_snapshot = {"updated_at": 10, "items": {"name:a": {"name": "A"}}}
    data = {"suppliers": {"Tradex": {"old": old_snapshot}}}
    new_snapshot = {"updated_at": 20, "items": {"name:b": {"name": "B"}}}

    assert latest_supplier_snapshot(data, "Tradex") == old_snapshot

    updated = upsert_supplier_snapshot(data, "Tradex", "new-session", new_snapshot, max_sessions=2)

    assert updated["suppliers"]["Tradex"] == {
        "new-session": new_snapshot,
        "old": old_snapshot,
    }


def test_latest_supplier_snapshot_accepts_legacy_flat_snapshot_shape():
    legacy_snapshot = {"updated_at": 10, "items": {"name:a": {"name": "A"}}}

    assert latest_supplier_snapshot({"suppliers": {"Tradex": legacy_snapshot}}, "Tradex") == legacy_snapshot


def test_api_fetch_history_round_trip_is_sorted_and_limited(tmp_path, monkeypatch):
    history_file = tmp_path / "api_fetch_history.json"
    monkeypatch.setattr(supplier_snapshots, "API_FETCH_HISTORY_FILE", history_file)

    append_api_fetch_history({"source": "old", "finished_at": 1})
    append_api_fetch_history({"source": "new", "finished_at": 2})

    assert get_api_fetch_history(limit=1) == [{"source": "new", "finished_at": 2}]


def test_session_supplier_diff_round_trip(tmp_path):
    save_session_supplier_diff(tmp_path, {"new_count": 2})

    assert load_session_supplier_diff(tmp_path) == {"new_count": 2}
