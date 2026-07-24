"""Tests for SQLite-backed category state documents."""

import json

from price_mixer.db import Database
from price_mixer.services import category_state_store as svc


def test_explicit_category_state_path_remains_json_only(tmp_path):
    path = tmp_path / "visibility.json"
    payload = {"IVEN": ["SSD"]}

    svc.save_category_state(
        payload,
        svc.CATEGORY_VISIBILITY_STATE,
        path,
        sqlite_primary=False,
    )

    assert svc.load_category_state(
        svc.CATEGORY_VISIBILITY_STATE,
        path,
        sqlite_primary=False,
    ) == payload


def test_category_state_migrates_once_and_keeps_json_backup(tmp_path):
    path = tmp_path / "overrides.json"
    original = {"name:ssd": "SSD", "name:mouse": "Mouse"}
    path.write_text(json.dumps(original), encoding="utf-8")
    db = Database(tmp_path / "state.db")
    svc.clear_category_state_cache()

    migrated = svc.load_category_state(
        svc.CATEGORY_OVERRIDES_STATE,
        path,
        get_db_func=lambda: db,
    )
    current = {"name:ssd": "Storage"}
    svc.save_category_state(
        current,
        svc.CATEGORY_OVERRIDES_STATE,
        path,
        get_db_func=lambda: db,
    )

    assert migrated == original
    assert svc.load_category_state(
        svc.CATEGORY_OVERRIDES_STATE,
        path,
        get_db_func=lambda: db,
    ) == current
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_category_state_cache_invalidates_on_external_revision(tmp_path):
    path = tmp_path / "markups.json"
    path.write_text(json.dumps({"SSD": {"percent": 10}}), encoding="utf-8")
    db = Database(tmp_path / "state.db")
    svc.clear_category_state_cache()

    first = svc.load_category_state(
        svc.CATEGORY_MARKUPS_STATE,
        path,
        get_db_func=lambda: db,
    )
    db.set_runtime_state_json(svc.CATEGORY_MARKUPS_STATE, {"SSD": {"percent": 20}})
    second = svc.load_category_state(
        svc.CATEGORY_MARKUPS_STATE,
        path,
        get_db_func=lambda: db,
    )

    assert first["SSD"]["percent"] == 10
    assert second["SSD"]["percent"] == 20


def test_category_state_signature_changes_after_save(tmp_path, monkeypatch):
    path = tmp_path / "visibility.json"
    path.write_text("{}", encoding="utf-8")
    db = Database(tmp_path / "state.db")
    svc.clear_category_state_cache()
    monkeypatch.setitem(svc.CATEGORY_STATE_PATHS, svc.CATEGORY_VISIBILITY_STATE, path)

    first = svc.category_state_signature(
        [svc.CATEGORY_VISIBILITY_STATE],
        get_db_func=lambda: db,
    )
    svc.save_category_state(
        {"Tradex": ["Mouse"]},
        svc.CATEGORY_VISIBILITY_STATE,
        path,
        get_db_func=lambda: db,
    )
    second = svc.category_state_signature(
        [svc.CATEGORY_VISIBILITY_STATE],
        get_db_func=lambda: db,
    )

    assert first != second
