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


def get_db() -> Database:
    return Database()
