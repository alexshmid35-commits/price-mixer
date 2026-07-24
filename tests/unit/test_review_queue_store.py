"""Tests for SQLite-backed review queue persistence."""

import json

from price_mixer.db import Database
from price_mixer.services import review_queue_store as svc


def test_explicit_path_remains_json_only(tmp_path):
    path = tmp_path / "queue.json"
    queue = {"ssd": {"name": "SSD", "supplier": "IVEN"}}

    svc.save_review_queue(queue, path=path)

    assert svc.load_review_queue(path=path) == queue


def test_default_load_migrates_json_to_sqlite_once(tmp_path, monkeypatch):
    path = tmp_path / "queue.json"
    original = {"ssd": {"name": "SSD", "candidates": [{"id": "123"}]}}
    path.write_text(json.dumps(original), encoding="utf-8")
    db = Database(tmp_path / "state.db")
    monkeypatch.setattr(svc, "REVIEW_QUEUE_FILE", path)

    assert svc.load_review_queue(get_db_func=lambda: db) == original
    assert db.get_state_meta(svc.REVIEW_QUEUE_MIGRATION_KEY) == "1"

    path.write_text(json.dumps({"replacement": {"name": "other"}}), encoding="utf-8")
    assert svc.load_review_queue(get_db_func=lambda: db) == original


def test_default_save_updates_sqlite_and_keeps_migration_backup(tmp_path, monkeypatch):
    path = tmp_path / "queue.json"
    original = {"old": {"name": "Old"}}
    path.write_text(json.dumps(original), encoding="utf-8")
    db = Database(tmp_path / "state.db")
    monkeypatch.setattr(svc, "REVIEW_QUEUE_FILE", path)
    svc.load_review_queue(get_db_func=lambda: db)

    current = {"new": {"name": "New", "supplier": "Tradex"}}
    svc.save_review_queue(current, get_db_func=lambda: db)

    assert svc.load_review_queue(get_db_func=lambda: db) == current
    assert json.loads(path.read_text(encoding="utf-8")) == original
