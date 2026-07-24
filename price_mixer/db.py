"""SQLite database abstraction layer."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from price_mixer.runtime_paths import get_runtime_paths
from price_mixer.services.sqlite_runtime import connect_sqlite


DB_PATH = get_runtime_paths().data_file("onliner_products.db")
_DB_LOCK = threading.RLock()


class Database:
    """Thread-safe wrapper around the SQLite database."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else DB_PATH

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(
            self.path,
            check_same_thread=False,
            row_factory=sqlite3.Row,
            wal=True,
        )

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with _DB_LOCK:
            with self._connect() as conn:
                return conn.execute(sql, params)

    def executemany(self, sql: str, params: list[tuple[Any, ...]]) -> sqlite3.Cursor:
        with _DB_LOCK:
            with self._connect() as conn:
                return conn.executemany(sql, params)

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with _DB_LOCK:
            with self._connect() as conn:
                row = conn.execute(sql, params).fetchone()
                return dict(row) if row else None

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with _DB_LOCK:
            with self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()
                return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Existing tables helpers (onliner_catalog, name_index)
    # ------------------------------------------------------------------

    def get_catalog_by_id(self, onliner_id: str) -> dict[str, Any] | None:
        return self.fetchone(
            "SELECT * FROM onliner_catalog WHERE onliner_id = ?", (onliner_id,)
        )

    def search_catalog_by_name(self, name_substring: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.fetchall(
            "SELECT * FROM onliner_catalog WHERE name LIKE ? LIMIT ?",
            (f"%{name_substring}%", limit),
        )

    def get_name_index(self, name_key: str) -> dict[str, Any] | None:
        return self.fetchone(
            "SELECT * FROM name_index WHERE name_key = ?", (name_key,)
        )

    # ------------------------------------------------------------------
    # Schema definitions for future migrations (Step 8)
    # ------------------------------------------------------------------

    MIGRATIONS: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS manual_bindings (
            name_key    TEXT PRIMARY KEY,
            onliner_id  TEXT NOT NULL,
            url         TEXT DEFAULT '',
            record_json TEXT NOT NULL DEFAULT '{}',
            confirmed_by TEXT DEFAULT '',
            confirmed_at INTEGER DEFAULT 0
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS id_change_journal (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          INTEGER NOT NULL,
            action      TEXT NOT NULL,
            session_dir TEXT DEFAULT '',
            source      TEXT DEFAULT '',
            changes_json TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS review_queue (
            queue_key   TEXT PRIMARY KEY,
            entry_json TEXT NOT NULL,
            updated_at INTEGER DEFAULT 0
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS category_overrides_db (
            category    TEXT PRIMARY KEY,
            overrides_json TEXT NOT NULL,
            updated_at  INTEGER DEFAULT 0
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS supplier_snapshots_db (
            supplier    TEXT NOT NULL,
            session_id  TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            created_at  INTEGER DEFAULT 0,
            PRIMARY KEY (supplier, session_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS runtime_state_meta (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            updated_at  INTEGER DEFAULT 0
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS runtime_state_json (
            state_key   TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            revision    INTEGER NOT NULL DEFAULT 0,
            updated_at  INTEGER DEFAULT 0
        );
        """,
    ]

    def run_migrations(self) -> None:
        with _DB_LOCK:
            with self._connect() as conn:
                for sql in self.MIGRATIONS:
                    conn.execute(sql)
                manual_columns = {
                    str(row[1])
                    for row in conn.execute("PRAGMA table_info(manual_bindings)").fetchall()
                }
                if "record_json" not in manual_columns:
                    conn.execute(
                        "ALTER TABLE manual_bindings "
                        "ADD COLUMN record_json TEXT NOT NULL DEFAULT '{}'"
                    )
                journal_columns = {
                    str(row[1])
                    for row in conn.execute("PRAGMA table_info(id_change_journal)").fetchall()
                }
                if "session_dir" not in journal_columns:
                    conn.execute(
                        "ALTER TABLE id_change_journal "
                        "ADD COLUMN session_dir TEXT DEFAULT ''"
                    )
                conn.commit()



    # ------------------------------------------------------------------
    # Manual ID bindings
    # ------------------------------------------------------------------

    def get_manual_bindings(self) -> dict[str, dict[str, Any]]:
        rows = self.fetchall(
            "SELECT name_key, onliner_id, url, record_json FROM manual_bindings"
        )
        result = {}
        for row in rows:
            try:
                record = json.loads(row.get("record_json") or "{}")
            except Exception:
                record = {}
            if not isinstance(record, dict):
                record = {}
            record.setdefault("id", str(row.get("onliner_id") or ""))
            record.setdefault("url", str(row.get("url") or ""))
            result[str(row["name_key"])] = record
        return result

    def replace_manual_bindings(self, bindings: dict[str, dict[str, Any]]) -> None:
        now = int(time.time())
        rows = []
        for name_key, raw_record in (bindings or {}).items():
            record = dict(raw_record or {})
            rows.append((
                str(name_key),
                str(record.get("id", "") or ""),
                str(record.get("url", "") or ""),
                json.dumps(record, ensure_ascii=False, separators=(",", ":")),
                now,
            ))
        with _DB_LOCK:
            with self._connect() as conn:
                conn.execute("DELETE FROM manual_bindings")
                if rows:
                    conn.executemany(
                        "INSERT INTO manual_bindings "
                        "(name_key, onliner_id, url, record_json, confirmed_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        rows,
                    )
                conn.commit()

    def set_manual_binding(self, name_key: str, onliner_id: str, url: str = "", confirmed_by: str = "") -> None:
        record = {"id": str(onliner_id or ""), "url": str(url or "")}
        with _DB_LOCK:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO manual_bindings "
                    "(name_key, onliner_id, url, record_json, confirmed_by, confirmed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        name_key,
                        onliner_id,
                        url,
                        json.dumps(record, ensure_ascii=False, separators=(",", ":")),
                        confirmed_by,
                        int(time.time()),
                    ),
                )
                conn.commit()

    def get_state_meta(self, key: str) -> str:
        row = self.fetchone("SELECT value FROM runtime_state_meta WHERE key = ?", (key,))
        return str((row or {}).get("value", "") or "")

    def set_state_meta(self, key: str, value: str) -> None:
        with _DB_LOCK:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO runtime_state_meta (key, value, updated_at) "
                    "VALUES (?, ?, ?)",
                    (str(key), str(value), int(time.time())),
                )
                conn.commit()

    def get_runtime_state_json(self, state_key: str) -> tuple[Any, int]:
        row = self.fetchone(
            "SELECT payload_json, revision FROM runtime_state_json WHERE state_key = ?",
            (str(state_key),),
        )
        if not row:
            return {}, 0
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except Exception:
            payload = {}
        return payload, int(row.get("revision", 0) or 0)

    def set_runtime_state_json(self, state_key: str, payload: Any) -> int:
        with _DB_LOCK:
            with self._connect() as conn:
                previous = conn.execute(
                    "SELECT revision FROM runtime_state_json WHERE state_key = ?",
                    (str(state_key),),
                ).fetchone()
                previous_revision = int(previous[0] or 0) if previous else 0
                revision = max(time.time_ns(), previous_revision + 1)
                conn.execute(
                    "INSERT OR REPLACE INTO runtime_state_json "
                    "(state_key, payload_json, revision, updated_at) VALUES (?, ?, ?, ?)",
                    (
                        str(state_key),
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        revision,
                        int(time.time()),
                    ),
                )
                conn.commit()
        return revision

    def get_runtime_state_revisions(self, state_keys: list[str]) -> dict[str, int]:
        keys = [str(key) for key in state_keys if str(key or "").strip()]
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        rows = self.fetchall(
            f"SELECT state_key, revision FROM runtime_state_json WHERE state_key IN ({placeholders})",
            tuple(keys),
        )
        revisions = {str(row["state_key"]): int(row.get("revision", 0) or 0) for row in rows}
        return {key: revisions.get(key, 0) for key in keys}

    # ------------------------------------------------------------------
    # ID change journal
    # ------------------------------------------------------------------

    def get_id_journal(self, limit: int = 10000) -> list[dict[str, Any]]:
        rows = self.fetchall(
            "SELECT ts, action, session_dir, source, changes_json FROM ("
            "SELECT id, ts, action, session_dir, source, changes_json "
            "FROM id_change_journal ORDER BY id DESC LIMIT ?"
            ") ORDER BY id ASC",
            (limit,),
        )
        result = []
        for r in rows:
            try:
                changes = json.loads(r["changes_json"])
            except Exception:
                changes = []
            result.append({
                "ts": r["ts"],
                "action": r["action"],
                "session_dir": r.get("session_dir", ""),
                "source": r["source"],
                "changes": changes,
            })
        return result

    def replace_id_journal(self, rows: list[dict[str, Any]], limit: int = 10000) -> None:
        payload = list(rows or [])[-max(0, int(limit or 0)):]
        values = [(
            int(row.get("ts", 0) or 0),
            str(row.get("action", "") or ""),
            str(row.get("session_dir", "") or ""),
            str(row.get("source", "") or ""),
            json.dumps(row.get("changes", []), ensure_ascii=False, separators=(",", ":")),
        ) for row in payload if isinstance(row, dict)]
        with _DB_LOCK:
            with self._connect() as conn:
                conn.execute("DELETE FROM id_change_journal")
                if values:
                    conn.executemany(
                        "INSERT INTO id_change_journal "
                        "(ts, action, session_dir, source, changes_json) VALUES (?, ?, ?, ?, ?)",
                        values,
                    )
                conn.commit()

    def append_id_journal(
        self,
        ts: int,
        action: str,
        source: str,
        changes: list[dict[str, Any]],
        session_dir: str = "",
        limit: int = 10000,
    ) -> None:
        with _DB_LOCK:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO id_change_journal "
                    "(ts, action, session_dir, source, changes_json) VALUES (?, ?, ?, ?, ?)",
                    (
                        ts,
                        action,
                        str(session_dir or ""),
                        source,
                        json.dumps(changes, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                keep = max(0, int(limit or 0))
                if keep:
                    conn.execute(
                        "DELETE FROM id_change_journal WHERE id NOT IN ("
                        "SELECT id FROM id_change_journal ORDER BY id DESC LIMIT ?"
                        ")",
                        (keep,),
                    )
                else:
                    conn.execute("DELETE FROM id_change_journal")
                conn.commit()

    # ------------------------------------------------------------------
    # Review queue
    # ------------------------------------------------------------------

    def get_review_queue(self) -> dict[str, dict[str, Any]]:
        rows = self.fetchall("SELECT queue_key, entry_json FROM review_queue")
        result = {}
        for row in rows:
            try:
                entry = json.loads(row.get("entry_json") or "{}")
            except Exception:
                entry = {}
            if isinstance(entry, dict):
                result[str(row["queue_key"])] = entry
        return result

    def replace_review_queue(self, queue: dict[str, dict[str, Any]]) -> None:
        now = int(time.time())
        values = [
            (
                str(queue_key),
                json.dumps(entry, ensure_ascii=False, separators=(",", ":")),
                now,
            )
            for queue_key, entry in (queue or {}).items()
            if str(queue_key or "").strip() and isinstance(entry, dict)
        ]
        with _DB_LOCK:
            with self._connect() as conn:
                conn.execute("DELETE FROM review_queue")
                if values:
                    conn.executemany(
                        "INSERT INTO review_queue (queue_key, entry_json, updated_at) "
                        "VALUES (?, ?, ?)",
                        values,
                    )
                conn.commit()

    # ------------------------------------------------------------------
    # Category overrides
    # ------------------------------------------------------------------

    def get_category_overrides(self) -> dict[str, Any]:
        rows = self.fetchall("SELECT category, overrides_json FROM category_overrides_db")
        result = {}
        for r in rows:
            try:
                result[r["category"]] = json.loads(r["overrides_json"])
            except Exception:
                pass
        return result

    def set_category_overrides(self, category: str, overrides: Any) -> None:
        with _DB_LOCK:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO category_overrides_db (category, overrides_json, updated_at) VALUES (?, ?, ?)",
                    (category, json.dumps(overrides, ensure_ascii=False), int(time.time())),
                )
                conn.commit()

    def clear_category_overrides(self) -> None:
        with _DB_LOCK:
            with self._connect() as conn:
                conn.execute("DELETE FROM category_overrides_db")
                conn.commit()

    # ------------------------------------------------------------------
    # Supplier snapshots
    # ------------------------------------------------------------------

    def get_supplier_snapshots(self) -> dict[str, dict[str, Any]]:
        rows = self.fetchall("SELECT supplier, session_id, snapshot_json FROM supplier_snapshots_db")
        result: dict[str, dict[str, Any]] = {}
        for r in rows:
            try:
                snapshot = json.loads(r["snapshot_json"])
            except Exception:
                snapshot = {}
            supplier = r["supplier"]
            session_id = r["session_id"]
            if supplier not in result:
                result[supplier] = {}
            result[supplier][session_id] = snapshot
        return {"suppliers": result}

    def set_supplier_snapshot(self, supplier: str, session_id: str, snapshot: Any) -> None:
        with _DB_LOCK:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO supplier_snapshots_db (supplier, session_id, snapshot_json, created_at) VALUES (?, ?, ?, ?)",
                    (supplier, session_id, json.dumps(snapshot, ensure_ascii=False), int(time.time())),
                )
                conn.commit()

    def clear_supplier_snapshots(self) -> None:
        with _DB_LOCK:
            with self._connect() as conn:
                conn.execute("DELETE FROM supplier_snapshots_db")
                conn.commit()

def get_db() -> Database:
    return Database()
