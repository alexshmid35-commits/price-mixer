"""SQLite working store for consolidated supplier-price sessions."""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import threading
import time


SCHEMA_VERSION = 5
PAGE_COLUMNS = {
    0: "onliner_id",
    1: "name_key",
    2: "price",
    3: "supplier_key",
    4: "warranty_key",
    5: "delivery_key",
    6: "rrc",
    7: "no_discount",
    8: "row_index",
    9: "category_key",
}
NUMERIC_COLUMNS = {2, 6, 7, 8}


class SessionProductStore:
    """Owns indexed session rows while JSON/XLSX remain compatibility snapshots."""

    def __init__(self, path, *, mode="off"):
        self.path = Path(path).resolve()
        normalized_mode = str(mode or "off").strip().casefold()
        self.mode = normalized_mode if normalized_mode in {"off", "dual", "canonical"} else "off"
        self._init_lock = threading.Lock()
        self._initialized = False

    @property
    def enabled(self):
        return self.mode != "off"

    @property
    def canonical(self):
        return self.mode == "canonical"

    def connection(self):
        self._ensure_schema()
        connection = sqlite3.connect(
            str(self.path),
            timeout=30,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _ensure_schema(self):
        if self._initialized or not self.enabled:
            return
        with self._init_lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(str(self.path), timeout=30)) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=NORMAL")
                connection.execute("PRAGMA busy_timeout=30000")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS session_product_meta (
                        session_id TEXT PRIMARY KEY,
                        source_revision TEXT NOT NULL,
                        revision INTEGER NOT NULL,
                        row_count INTEGER NOT NULL,
                        rows_sha256 TEXT NOT NULL,
                        badge_counts_json TEXT NOT NULL DEFAULT '{}',
                        page_meta_json TEXT NOT NULL DEFAULT '{}',
                        updated_at INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS session_products (
                        session_id TEXT NOT NULL,
                        row_index INTEGER NOT NULL,
                        onliner_id TEXT NOT NULL DEFAULT '',
                        name TEXT NOT NULL DEFAULT '',
                        price REAL,
                        supplier TEXT NOT NULL DEFAULT '',
                        warranty TEXT NOT NULL DEFAULT '',
                        delivery_days TEXT NOT NULL DEFAULT '',
                        rrc REAL,
                        no_discount REAL,
                        category TEXT NOT NULL DEFAULT '',
                        name_key TEXT NOT NULL DEFAULT '',
                        supplier_key TEXT NOT NULL DEFAULT '',
                        warranty_key TEXT NOT NULL DEFAULT '',
                        delivery_key TEXT NOT NULL DEFAULT '',
                        category_key TEXT NOT NULL DEFAULT '',
                        search_text TEXT NOT NULL DEFAULT '',
                        row_json TEXT NOT NULL DEFAULT '[]',
                        source_position INTEGER NOT NULL DEFAULT 0,
                        revision INTEGER NOT NULL,
                        PRIMARY KEY (session_id, row_index),
                        FOREIGN KEY (session_id)
                            REFERENCES session_product_meta(session_id)
                            ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_session_products_id
                        ON session_products(session_id, onliner_id);
                    CREATE INDEX IF NOT EXISTS idx_session_products_supplier
                        ON session_products(session_id, supplier_key);
                    CREATE INDEX IF NOT EXISTS idx_session_products_category
                        ON session_products(session_id, category_key);
                    CREATE INDEX IF NOT EXISTS idx_session_products_price
                        ON session_products(session_id, price);
                    CREATE INDEX IF NOT EXISTS idx_session_products_name
                        ON session_products(session_id, name_key);
                    CREATE VIRTUAL TABLE IF NOT EXISTS session_products_fts
                        USING fts5(
                            session_id UNINDEXED,
                            row_index UNINDEXED,
                            search_text,
                            tokenize='trigram'
                        );
                    CREATE TABLE IF NOT EXISTS session_product_schema (
                        version INTEGER NOT NULL
                    );
                    """
                )
                row = connection.execute(
                    "SELECT version FROM session_product_schema LIMIT 1"
                ).fetchone()
                _ensure_column(
                    connection,
                    "session_product_meta",
                    "page_meta_json",
                    "TEXT NOT NULL DEFAULT '{}'",
                )
                _ensure_column(
                    connection,
                    "session_products",
                    "row_json",
                    "TEXT NOT NULL DEFAULT '[]'",
                )
                _ensure_column(
                    connection,
                    "session_products",
                    "source_position",
                    "INTEGER NOT NULL DEFAULT 0",
                )
                if row is None:
                    connection.execute(
                        "INSERT INTO session_product_schema(version) VALUES (?)",
                        (SCHEMA_VERSION,),
                    )
                elif int(row[0]) > SCHEMA_VERSION:
                    raise RuntimeError("Unsupported session product schema version")
                elif int(row[0]) < SCHEMA_VERSION:
                    connection.execute(
                        "UPDATE session_product_schema SET version=?",
                        (SCHEMA_VERSION,),
                    )
                connection.commit()
            self._initialized = True

    @staticmethod
    def session_id(session_dir):
        return Path(session_dir).resolve().name

    def replace_rows(
        self,
        session_dir,
        rows,
        *,
        source_revision,
        badge_counts=None,
    ):
        if not self.enabled:
            return {"status": "disabled", "changed": False}
        session_id = self.session_id(session_dir)
        with self.connection() as connection:
            current = connection.execute(
                "SELECT source_revision,row_count,rows_sha256,revision "
                "FROM session_product_meta WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if current is not None and str(current["source_revision"]) == str(source_revision):
                return {
                    "status": "ok",
                    "changed": False,
                    "revision": int(current["revision"]),
                    "row_count": int(current["row_count"]),
                    "rows_sha256": str(current["rows_sha256"]),
                }
            normalized = [_normalize_row(row, position) for position, row in enumerate(rows or [])]
            digest = rows_digest(normalized)
            resolved_badge_counts = (
                badge_counts()
                if callable(badge_counts)
                else badge_counts
            )
            page_meta = _build_page_meta(normalized)
            revision = int(current["revision"]) + 1 if current is not None else 1
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM session_products WHERE session_id=?",
                (session_id,),
            )
            connection.execute(
                "DELETE FROM session_products_fts WHERE session_id=?",
                (session_id,),
            )
            connection.execute(
                "INSERT INTO session_product_meta "
                "(session_id,source_revision,revision,row_count,rows_sha256,"
                "badge_counts_json,page_meta_json,updated_at) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "source_revision=excluded.source_revision,"
                "revision=excluded.revision,row_count=excluded.row_count,"
                "rows_sha256=excluded.rows_sha256,"
                "badge_counts_json=excluded.badge_counts_json,"
                "page_meta_json=excluded.page_meta_json,"
                "updated_at=excluded.updated_at",
                (
                    session_id,
                    str(source_revision),
                    revision,
                    len(normalized),
                    digest,
                    json.dumps(
                        resolved_badge_counts or {},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(
                        page_meta,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    int(time.time()),
                ),
            )
            connection.executemany(
                "INSERT INTO session_products "
                "(session_id,row_index,onliner_id,name,price,supplier,warranty,"
                "delivery_days,rrc,no_discount,category,name_key,supplier_key,"
                "warranty_key,delivery_key,category_key,search_text,row_json,"
                "source_position,revision) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        session_id,
                        item["row_index"],
                        item["onliner_id"],
                        item["name"],
                        item["price"],
                        item["supplier"],
                        item["warranty"],
                        item["delivery_days"],
                        item["rrc"],
                        item["no_discount"],
                        item["category"],
                        item["name_key"],
                        item["supplier_key"],
                        item["warranty_key"],
                        item["delivery_key"],
                        item["category_key"],
                        item["search_text"],
                        item["row_json"],
                        item["source_position"],
                        revision,
                    )
                    for item in normalized
                ],
            )
            connection.executemany(
                "INSERT INTO session_products_fts "
                "(session_id,row_index,search_text) VALUES (?,?,?)",
                [
                    (
                        session_id,
                        item["row_index"],
                        item["search_text"],
                    )
                    for item in normalized
                ],
            )
            connection.commit()
        return {
            "status": "ok",
            "changed": True,
            "revision": revision,
            "row_count": len(normalized),
            "rows_sha256": digest,
        }

    def parity(self, session_dir, rows):
        if not self.enabled:
            return {"status": "disabled"}
        session_id = self.session_id(session_dir)
        normalized = [_normalize_row(row, position) for position, row in enumerate(rows or [])]
        expected_digest = rows_digest(normalized)
        with self.connection() as connection:
            meta = connection.execute(
                "SELECT row_count,rows_sha256,revision FROM session_product_meta "
                "WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if meta is None:
            return {"status": "missing", "expected_rows": len(normalized)}
        matches = (
            int(meta["row_count"]) == len(normalized)
            and str(meta["rows_sha256"]) == expected_digest
        )
        return {
            "status": "ok" if matches else "mismatch",
            "matches": matches,
            "expected_rows": len(normalized),
            "stored_rows": int(meta["row_count"]),
            "revision": int(meta["revision"]),
            "expected_sha256": expected_digest,
            "stored_sha256": str(meta["rows_sha256"]),
        }

    def query_page(
        self,
        session_dir,
        *,
        draw=0,
        start=0,
        length=100,
        search="",
        order_specs=None,
        filter_mode="all",
        no_id_category="",
    ):
        if not self.canonical:
            return None
        session_id = self.session_id(session_dir)
        where = ["session_id=?"]
        params = [session_id]
        mode = str(filter_mode or "all").strip().casefold()
        if mode == "no_id":
            where.append("onliner_id=''")
            selected = _key(no_id_category)
            if selected:
                where.append("category_key=?")
                params.append(selected)
        elif mode == "duplicate":
            where.append(
                "onliner_id<>'' AND onliner_id IN ("
                "SELECT onliner_id FROM session_products "
                "WHERE session_id=? AND onliner_id<>'' "
                "GROUP BY onliner_id HAVING COUNT(*)>1)"
            )
            params.append(session_id)
        elif mode != "all":
            return None
        query = _key(search)
        if query:
            if len(query) >= 3:
                where.append(
                    "row_index IN ("
                    "SELECT row_index FROM session_products_fts "
                    "WHERE session_id=? AND session_products_fts MATCH ?)"
                )
                params.extend([session_id, _fts_literal(query)])
            else:
                where.append("instr(search_text,?)>0")
                params.append(query)
        where_sql = " AND ".join(where)
        order_sql = _order_sql(order_specs)
        page_start = max(0, int(start or 0))
        page_length = min(500, max(10, int(length or 100)))

        with self.connection() as connection:
            meta = connection.execute(
                "SELECT row_count,badge_counts_json,page_meta_json "
                "FROM session_product_meta "
                "WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if meta is None:
                return None
            filtered_count = int(connection.execute(
                f"SELECT COUNT(*) FROM session_products WHERE {where_sql}",
                params,
            ).fetchone()[0])
            page_rows = connection.execute(
                "SELECT onliner_id,name,price,supplier,warranty,delivery_days,"
                "rrc,no_discount,row_index,category,row_json "
                f"FROM session_products WHERE {where_sql} "
                f"ORDER BY {order_sql} LIMIT ? OFFSET ?",
                [*params, page_length, page_start],
            ).fetchall()
            page_ids = sorted({
                str(row["onliner_id"] or "")
                for row in page_rows
                if str(row["onliner_id"] or "")
            })
            duplicate_meta = self._page_duplicate_meta(
                connection,
                session_id,
                page_ids,
            )
        try:
            badge_counts = json.loads(str(meta["badge_counts_json"] or "{}"))
        except json.JSONDecodeError:
            badge_counts = {}
        try:
            page_meta = json.loads(str(meta["page_meta_json"] or "{}"))
        except json.JSONDecodeError:
            page_meta = {}
        categories = list(page_meta.get("without_id_category_counts", []) or [])
        return {
            "draw": max(0, int(draw or 0)),
            "recordsTotal": int(meta["row_count"]),
            "recordsFiltered": filtered_count,
            "data": [_db_row_to_page(row) for row in page_rows],
            "meta": {
                "duplicate_ids": duplicate_meta,
                "duplicate_id_count": int(page_meta.get("duplicate_id_count", 0) or 0),
                "duplicate_row_count": int(page_meta.get("duplicate_row_count", 0) or 0),
                "without_id_category_counts": categories,
                "without_id_count": int(page_meta.get("without_id_count", 0) or 0),
                "supplier_count": max(1, int(page_meta.get("supplier_count", 0) or 0)),
                "badge_counts": badge_counts if isinstance(badge_counts, dict) else {},
                "storage": "sqlite",
            },
        }

    @staticmethod
    def _page_duplicate_meta(connection, session_id, page_ids):
        if not page_ids:
            return {}
        placeholders = ",".join("?" for _ in page_ids)
        rows = connection.execute(
            "SELECT onliner_id,COUNT(*) AS item_count,MIN(price) AS min_price,"
            "MAX(price) AS max_price FROM session_products "
            f"WHERE session_id=? AND onliner_id IN ({placeholders}) "
            "GROUP BY onliner_id HAVING COUNT(*)>1",
            [session_id, *page_ids],
        ).fetchall()
        return {
            str(row["onliner_id"]): [
                int(row["item_count"]),
                row["min_price"],
                row["max_price"],
            ]
            for row in rows
        }

    def delete_session(self, session_dir):
        if not self.enabled:
            return
        with self.connection() as connection:
            session_id = self.session_id(session_dir)
            connection.execute(
                "DELETE FROM session_products_fts WHERE session_id=?",
                (session_id,),
            )
            connection.execute(
                "DELETE FROM session_product_meta WHERE session_id=?",
                (session_id,),
            )
            connection.commit()


def rows_digest(normalized_rows):
    digest = hashlib.sha256()
    for item in normalized_rows:
        payload = [
            item["onliner_id"],
            item["name"],
            item["price"],
            item["supplier"],
            item["warranty"],
            item["delivery_days"],
            item["rrc"],
            item["no_discount"],
            item["row_index"],
            item["category"],
        ]
        digest.update(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _normalize_row(row, position):
    padded = list(row if isinstance(row, (list, tuple)) else []) + [""] * 10
    try:
        row_index = int(padded[8])
    except (TypeError, ValueError):
        row_index = int(position)
    values = {
        "onliner_id": _text(padded[0]),
        "name": _text(padded[1]),
        "price": _number(padded[2]),
        "supplier": _text(padded[3]),
        "warranty": _text(padded[4]),
        "delivery_days": _text(padded[5]),
        "rrc": _number(padded[6]),
        "no_discount": _number(padded[7]),
        "row_index": row_index,
        "category": _text(padded[9]),
        "source_position": int(position),
    }
    values["row_json"] = json.dumps(
        padded[:10],
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    values.update({
        "name_key": _key(values["name"]),
        "supplier_key": _key(values["supplier"]),
        "warranty_key": _key(values["warranty"]),
        "delivery_key": _key(values["delivery_days"]),
        "category_key": _key(values["category"]),
    })
    values["search_text"] = "\x1f".join(
        _key(value)
        for value in (
            values["onliner_id"],
            values["name"],
            values["price"],
            values["supplier"],
            values["warranty"],
            values["delivery_days"],
            values["rrc"],
            values["no_discount"],
            values["row_index"],
            values["category"],
        )
    )
    return values


def _build_page_meta(rows):
    id_counts = {}
    category_counts = {}
    suppliers = set()
    for item in rows:
        supplier = item["supplier"]
        if supplier:
            suppliers.add(supplier)
        onliner_id = item["onliner_id"]
        if onliner_id:
            id_counts[onliner_id] = int(id_counts.get(onliner_id, 0)) + 1
            continue
        category = item["category"] or "Без категории"
        category_counts[category] = int(category_counts.get(category, 0)) + 1
    duplicate_counts = [count for count in id_counts.values() if count > 1]
    categories = [
        {"category": category, "count": count}
        for category, count in sorted(
            category_counts.items(),
            key=lambda entry: entry[0].casefold(),
        )
    ]
    return {
        "duplicate_id_count": len(duplicate_counts),
        "duplicate_row_count": sum(duplicate_counts),
        "without_id_category_counts": categories,
        "without_id_count": sum(category_counts.values()),
        "supplier_count": max(1, len(suppliers)),
    }


def _db_row_to_page(row):
    try:
        raw = json.loads(str(row["row_json"] or "[]"))
    except (TypeError, json.JSONDecodeError):
        raw = None
    if isinstance(raw, list) and len(raw) >= 10:
        return raw[:10]
    return [
        str(row["onliner_id"] or ""),
        str(row["name"] or ""),
        _output_number(row["price"]),
        str(row["supplier"] or ""),
        str(row["warranty"] or ""),
        str(row["delivery_days"] or ""),
        _output_number(row["rrc"]),
        _output_number(row["no_discount"]),
        int(row["row_index"]),
        str(row["category"] or ""),
    ]


def _order_sql(order_specs):
    parts = []
    for raw_column, raw_direction in order_specs or []:
        try:
            column = int(raw_column)
        except (TypeError, ValueError):
            continue
        sql_column = PAGE_COLUMNS.get(column)
        if sql_column is None:
            continue
        direction = "DESC" if str(raw_direction or "asc").casefold() == "desc" else "ASC"
        if column not in NUMERIC_COLUMNS:
            parts.append(f"({sql_column}='') ASC")
        parts.append(f"{sql_column} {direction}")
    if not parts:
        return "(name_key='') ASC, name_key ASC, source_position ASC"
    parts.append("source_position ASC")
    return ", ".join(parts)


def _key(value):
    return str(value if value is not None else "").strip().casefold()


def _fts_literal(value):
    return '"' + str(value or "").replace('"', '""') + '"'


def _ensure_column(connection, table, column, declaration):
    columns = {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {declaration}"
        )


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return str(value).strip()


def _number(value):
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _output_number(value):
    if value is None:
        return ""
    number = float(value)
    return int(number) if number.is_integer() else round(number, 2)
