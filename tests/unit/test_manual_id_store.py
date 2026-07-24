"""Unit tests for manual ID binding and journal persistence."""

import json

from price_mixer.db import Database
from price_mixer.services import manual_id_store as svc


class FakeDb:
    def __init__(self, bindings=None):
        self.bindings = bindings or {}
        self.saved_bindings = []
        self.journal = []

    def get_manual_bindings(self):
        return self.bindings

    def set_manual_binding(self, name_key, onliner_id, url="", confirmed_by=""):
        self.saved_bindings.append((name_key, onliner_id, url))

    def append_id_journal(self, ts, action, source, changes):
        self.journal.append({
            "ts": ts,
            "action": action,
            "source": source,
            "changes": changes,
        })


def test_load_manual_id_bindings_reads_json_without_touching_db(tmp_path):
    path = tmp_path / "manual_id_bindings.json"
    svc.save_manual_id_bindings(
        {
            "ssd": {"id": "", "url": "", "blocked": True},
            "mouse": {"id": "111", "url": "old"},
        },
        path=path,
        get_db_func=lambda: FakeDb(),
    )
    fake_db = FakeDb({
        "ssd": {"id": "", "url": ""},
        "mouse": {"id": "222", "url": "new"},
            "keyboard": {"id": "333", "url": "db"},
    })

    result = svc.load_manual_id_bindings(path=path, get_db_func=lambda: fake_db)

    assert result["ssd"] == {"id": "", "url": "", "blocked": True}
    assert result["mouse"] == {"id": "111", "url": "old"}
    assert "keyboard" not in result


def test_save_manual_id_bindings_writes_full_json_without_sqlite(tmp_path):
    path = tmp_path / "manual_id_bindings.json"
    fake_db = FakeDb()

    svc.save_manual_id_bindings(
        {"ssd": {"id": " 00123 ", "url": " https://x ", "blocked": True}},
        path=path,
        get_db_func=lambda: fake_db,
    )

    assert svc.load_manual_id_bindings(path=path, get_db_func=lambda: FakeDb()) == {
        "ssd": {"id": "00123", "url": "https://x", "blocked": True}
    }
    assert fake_db.saved_bindings == []


def test_default_load_migrates_json_to_sqlite_once(tmp_path, monkeypatch):
    json_path = tmp_path / "manual_id_bindings.json"
    json_path.write_text(json.dumps({
        "supplier:iven:ssd": {
            "id": "123",
            "url": "https://example.test/123",
            "blocked": True,
            "suppliers": ["IVEN"],
        }
    }), encoding="utf-8")
    db = Database(tmp_path / "state.db")
    monkeypatch.setattr(svc, "MANUAL_ID_BINDINGS_FILE", json_path)

    migrated = svc.load_manual_id_bindings(get_db_func=lambda: db)

    assert migrated["supplier:iven:ssd"]["blocked"] is True
    assert migrated["supplier:iven:ssd"]["suppliers"] == ["IVEN"]
    assert db.get_state_meta(svc.MANUAL_BINDINGS_MIGRATION_KEY) == "1"

    json_path.write_text(json.dumps({"replacement": {"id": "999"}}), encoding="utf-8")
    assert svc.load_manual_id_bindings(get_db_func=lambda: db) == migrated


def test_default_save_updates_sqlite_and_json_backup(tmp_path, monkeypatch):
    json_path = tmp_path / "manual_id_bindings.json"
    json_path.write_text("{}", encoding="utf-8")
    db = Database(tmp_path / "state.db")
    monkeypatch.setattr(svc, "MANUAL_ID_BINDINGS_FILE", json_path)
    bindings = {
        "supplier:tradex:mouse": {
            "id": "456",
            "url": "https://example.test/456",
            "suppliers": ["Tradex"],
        }
    }

    svc.save_manual_id_bindings(bindings, get_db_func=lambda: db)

    assert svc.load_manual_id_bindings(get_db_func=lambda: db) == bindings
    assert json.loads(json_path.read_text(encoding="utf-8")) == bindings


def test_append_id_change_journal_preserves_session_for_rollback_without_sqlite(tmp_path):
    path = tmp_path / "id_change_journal.json"
    fake_db = FakeDb()

    svc.append_id_change_journal(
        {
            "ts": 123,
            "action": "manual_id_clear",
            "session_dir": "/tmp/session",
            "source": "test",
            "changes": [{"row_idx": 1}],
        },
        path=path,
        get_db_func=lambda: fake_db,
    )

    assert svc.load_id_change_journal(path=path) == [{
        "ts": 123,
        "action": "manual_id_clear",
        "session_dir": "/tmp/session",
        "source": "test",
        "changes": [{"row_idx": 1}],
    }]
    assert fake_db.journal == []


def test_default_id_journal_migrates_to_sqlite_and_appends_without_rewriting_backup(tmp_path, monkeypatch):
    json_path = tmp_path / "id_change_journal.json"
    original = [{
        "ts": 100,
        "action": "first",
        "session_dir": "session-a",
        "source": "test",
        "changes": [{"row_idx": 1}],
    }]
    json_path.write_text(json.dumps(original), encoding="utf-8")
    db = Database(tmp_path / "state.db")
    monkeypatch.setattr(svc, "ID_CHANGE_JOURNAL_FILE", json_path)

    assert svc.load_id_change_journal(get_db_func=lambda: db) == original
    assert db.get_state_meta(svc.ID_JOURNAL_MIGRATION_KEY) == "1"

    svc.append_id_change_journal(
        {
            "ts": 200,
            "action": "second",
            "session_dir": "session-b",
            "source": "test",
            "changes": [{"row_idx": 2}],
        },
        get_db_func=lambda: db,
    )

    loaded = svc.load_id_change_journal(get_db_func=lambda: db)
    assert [row["action"] for row in loaded] == ["first", "second"]
    assert loaded[-1]["session_dir"] == "session-b"
    assert json.loads(json_path.read_text(encoding="utf-8")) == original


def test_default_id_journal_save_replaces_sqlite_snapshot(tmp_path, monkeypatch):
    json_path = tmp_path / "id_change_journal.json"
    json_path.write_text("[]", encoding="utf-8")
    db = Database(tmp_path / "state.db")
    monkeypatch.setattr(svc, "ID_CHANGE_JOURNAL_FILE", json_path)
    rows = [
        {"ts": 1, "action": "one", "session_dir": "s", "source": "x", "changes": []},
        {"ts": 2, "action": "two", "session_dir": "s", "source": "x", "changes": []},
    ]

    svc.save_id_change_journal(rows, get_db_func=lambda: db)
    svc.save_id_change_journal(rows[:1], get_db_func=lambda: db)

    assert svc.load_id_change_journal(get_db_func=lambda: db) == rows[:1]


def test_is_manually_confirmed_id_uses_normalized_name_and_id():
    result = svc.is_manually_confirmed_id(
        "SSD Pro",
        " 00123 ",
        load_bindings=lambda: {"ssd pro": {"id": "00123", "url": ""}},
        normalize_name_key_func=lambda value: str(value).strip().lower(),
    )

    assert result is True


def test_is_manually_confirmed_id_ignores_blocked_binding():
    result = svc.is_manually_confirmed_id(
        "SSD Pro",
        "00123",
        load_bindings=lambda: {"ssd pro": {"id": "00123", "url": "", "blocked": True}},
        normalize_name_key_func=lambda value: str(value).strip().lower(),
    )

    assert result is False


def test_is_manually_confirmed_id_uses_supplier_scoped_binding():
    result = svc.is_manually_confirmed_id(
        "SSD Pro",
        "00123",
        supplier_name="IVEN_zakaz",
        load_bindings=lambda: {
            "supplier:iven_zakaz:ssd pro": {"id": "00123", "url": ""},
            "supplier:iven:ssd pro": {"id": "00999", "url": ""},
        },
        normalize_name_key_func=lambda value: str(value).strip().lower(),
    )

    assert result is True


def test_is_manually_confirmed_id_does_not_fall_back_to_unscoped_binding():
    result = svc.is_manually_confirmed_id(
        "SSD Pro",
        "00123",
        supplier_name="Tradex",
        load_bindings=lambda: {"ssd pro": {"id": "00123", "url": ""}},
        normalize_name_key_func=lambda value: str(value).strip().lower(),
    )

    assert result is False


def test_migrate_bindings_to_supplier_scope_preserves_and_splits_legacy_records():
    migrated, report = svc.migrate_bindings_to_supplier_scope(
        {
            "ssd pro": {"id": "123", "url": "u"},
            "mouse": {"id": "456", "url": "m", "suppliers": ["Tradex"]},
            "supplier:iven:keyboard": {"id": "789", "url": "k", "suppliers": ["IVEN"]},
        },
        suppliers_by_key={"ssd pro": ["IVEN", "IVEN_zakaz"]},
        default_suppliers=["N-Tech"],
    )

    assert "ssd pro" not in migrated
    assert migrated["supplier:iven:ssd pro"]["id"] == "123"
    assert migrated["supplier:iven_zakaz:ssd pro"]["id"] == "123"
    assert migrated["supplier:tradex:mouse"]["id"] == "456"
    assert migrated["supplier:iven:keyboard"]["id"] == "789"
    assert report == {"before": 3, "after": 4, "created_scoped": 3, "unresolved_global": 0}
