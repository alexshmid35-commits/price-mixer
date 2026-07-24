"""SQLite runtime state migration tests."""

import sqlite3

from price_mixer.db import Database


def test_run_migrations_upgrades_legacy_manual_bindings_table(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE manual_bindings ("
            "name_key TEXT PRIMARY KEY, onliner_id TEXT NOT NULL, url TEXT DEFAULT '', "
            "confirmed_by TEXT DEFAULT '', confirmed_at INTEGER DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO manual_bindings (name_key, onliner_id, url) VALUES (?, ?, ?)",
            ("ssd", "123", "https://example.test/123"),
        )

    db = Database(path)
    db.run_migrations()

    assert db.get_manual_bindings() == {
        "ssd": {"id": "123", "url": "https://example.test/123"}
    }


def test_run_migrations_upgrades_legacy_id_journal_and_preserves_order(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE id_change_journal ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, "
            "action TEXT NOT NULL, source TEXT DEFAULT '', changes_json TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO id_change_journal (ts, action, source, changes_json) "
            "VALUES (1, 'first', 'test', '[]')"
        )

    db = Database(path)
    db.run_migrations()
    db.append_id_journal(2, "second", "test", [{"row_idx": 2}], session_dir="session-b")

    assert db.get_id_journal() == [
        {"ts": 1, "action": "first", "session_dir": "", "source": "test", "changes": []},
        {
            "ts": 2,
            "action": "second",
            "session_dir": "session-b",
            "source": "test",
            "changes": [{"row_idx": 2}],
        },
    ]


def test_replace_review_queue_is_atomic_full_snapshot(tmp_path):
    db = Database(tmp_path / "state.db")
    db.run_migrations()

    db.replace_review_queue({"a": {"name": "A"}, "b": {"name": "B"}})
    assert db.get_review_queue() == {"a": {"name": "A"}, "b": {"name": "B"}}

    db.replace_review_queue({"b": {"name": "B2"}})
    assert db.get_review_queue() == {"b": {"name": "B2"}}


def test_runtime_state_json_round_trip_updates_revision(tmp_path):
    db = Database(tmp_path / "state.db")
    db.run_migrations()

    first_revision = db.set_runtime_state_json("category_visibility", {"IVEN": ["SSD"]})
    payload, loaded_revision = db.get_runtime_state_json("category_visibility")
    second_revision = db.set_runtime_state_json("category_visibility", {"IVEN": ["Mouse"]})

    assert payload == {"IVEN": ["SSD"]}
    assert loaded_revision == first_revision
    assert second_revision > first_revision
    assert db.get_runtime_state_revisions(["category_visibility", "missing"]) == {
        "category_visibility": second_revision,
        "missing": 0,
    }
