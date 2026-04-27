import json
"""SQLite database abstraction layer."""

import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple


DB_PATH = Path(__file__).parent.parent / "onliner_products.db"
_DB_LOCK = threading.RLock()


class Database:
    """Thread-safe wrapper around the SQLite database."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DB_PATH

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with _DB_LOCK:
            with self._connect() as conn:
                return conn.execute(sql, params)

    def executemany(self, sql: str, params: List[Tuple[Any, ...]]) -> sqlite3.Cursor:
        with _DB_LOCK:
            with self._connect() as conn:
                return conn.executemany(sql, params)

    def fetchone(self, sql: str, params: Tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
        with _DB_LOCK:
            with self._connect() as conn:
                row = conn.execute(sql, params).fetchone()
                return dict(row) if row else None

    def fetchall(self, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        with _DB_LOCK:
            with self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()
                return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Existing tables helpers (onliner_catalog, name_index)
    # ------------------------------------------------------------------

    def get_catalog_by_id(self, onliner_id: str) -> Optional[Dict[str, Any]]:
        return self.fetchone(
            "SELECT * FROM onliner_catalog WHERE onliner_id = ?", (onliner_id,)
        )

    def search_catalog_by_name(self, name_substring: str, limit: int = 20) -> List[Dict[str, Any]]:
        return self.fetchall(
            "SELECT * FROM onliner_catalog WHERE name LIKE ? LIMIT ?",
            (f"%{name_substring}%", limit),
        )

    def get_name_index(self, name_key: str) -> Optional[Dict[str, Any]]:
        return self.fetchone(
            "SELECT * FROM name_index WHERE name_key = ?", (name_key,)
        )

    # ------------------------------------------------------------------
    # Schema definitions for future migrations (Step 8)
    # ------------------------------------------------------------------

    MIGRATIONS: List[str] = [
        """
        CREATE TABLE IF NOT EXISTS manual_bindings (
            name_key    TEXT PRIMARY KEY,
            onliner_id  TEXT NOT NULL,
            url         TEXT DEFAULT '',
            confirmed_by TEXT DEFAULT '',
            confirmed_at INTEGER DEFAULT 0
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS id_change_journal (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          INTEGER NOT NULL,
            action      TEXT NOT NULL,
            source      TEXT DEFAULT '',
            changes_json TEXT NOT NULL
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
    ]

    def run_migrations(self) -> None:
        with _DB_LOCK:
            with self._connect() as conn:
                for sql in self.MIGRATIONS:
                    conn.execute(sql)
                conn.commit()



    # ------------------------------------------------------------------
    # Manual ID bindings
    # ------------------------------------------------------------------

    def get_manual_bindings(self) -> Dict[str, Dict[str, str]]:
        rows = self.fetchall("SELECT name_key, onliner_id, url FROM manual_bindings")
        return {r["name_key"]: {"id": r["onliner_id"], "url": r["url"]} for r in rows}

    def set_manual_binding(self, name_key: str, onliner_id: str, url: str = "", confirmed_by: str = "") -> None:
        with _DB_LOCK:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO manual_bindings (name_key, onliner_id, url, confirmed_by, confirmed_at) VALUES (?, ?, ?, ?, ?)",
                    (name_key, onliner_id, url, confirmed_by, int(time.time())),
                )
                conn.commit()

    # ------------------------------------------------------------------
    # ID change journal
    # ------------------------------------------------------------------

    def get_id_journal(self, limit: int = 10000) -> List[Dict[str, Any]]:
        rows = self.fetchall(
            "SELECT ts, action, source, changes_json FROM id_change_journal ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        result = []
        for r in rows:
            try:
                changes = json.loads(r["changes_json"])
            except Exception:
                changes = []
            result.append({"ts": r["ts"], "action": r["action"], "source": r["source"], "changes": changes})
        return result

    def append_id_journal(self, ts: int, action: str, source: str, changes: List[Dict[str, Any]]) -> None:
        with _DB_LOCK:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO id_change_journal (ts, action, source, changes_json) VALUES (?, ?, ?, ?)",
                    (ts, action, source, json.dumps(changes, ensure_ascii=False)),
                )
                conn.commit()

    # ------------------------------------------------------------------
    # Category overrides
    # ------------------------------------------------------------------

    def get_category_overrides(self) -> Dict[str, Any]:
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

    def get_supplier_snapshots(self) -> Dict[str, Dict[str, Any]]:
        rows = self.fetchall("SELECT supplier, session_id, snapshot_json FROM supplier_snapshots_db")
        result: Dict[str, Dict[str, Any]] = {}
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
