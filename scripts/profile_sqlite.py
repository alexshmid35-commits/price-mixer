#!/usr/bin/env python3
"""Profile Price Mixer SQLite query plans without external services."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def profile_database(path, *, kind):
    database = Path(path).resolve()
    result = {
        "path": str(database),
        "kind": str(kind),
        "bytes": database.stat().st_size if database.is_file() else 0,
        "status": "missing",
        "pragmas": {},
        "plans": {},
    }
    if not database.is_file():
        return result
    uri = f"file:{database}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            result["status"] = "ok"
            result["pragmas"] = {
                "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
                "page_size": int(connection.execute("PRAGMA page_size").fetchone()[0]),
                "page_count": int(connection.execute("PRAGMA page_count").fetchone()[0]),
                "freelist_count": int(connection.execute("PRAGMA freelist_count").fetchone()[0]),
            }
            if kind == "session":
                result.update(_profile_session(connection))
            elif kind == "catalog":
                result.update(_profile_catalog(connection))
            else:
                raise ValueError(f"unsupported profile kind: {kind}")
    except (OSError, sqlite3.Error, ValueError) as exc:
        result["status"] = "error"
        result["error"] = str(exc)
    return result


def _profile_session(connection):
    latest = connection.execute(
        "SELECT session_id,row_count,revision FROM session_product_meta "
        "WHERE complete=1 ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    if latest is None:
        return {"session": None, "plans": {}}
    session_id = str(latest["session_id"])
    queries = {
        "total_count": (
            "SELECT COUNT(*) FROM session_products WHERE session_id=?",
            (session_id,),
        ),
        "without_id_count": (
            "SELECT COUNT(*) FROM session_products WHERE session_id=? AND onliner_id=''",
            (session_id,),
        ),
        "ordered_name_page": (
            "SELECT row_index,name FROM session_products WHERE session_id=? ORDER BY name_key LIMIT 100",
            (session_id,),
        ),
        "without_id_categories": (
            "SELECT category_key,MIN(category),COUNT(*) "
            "FROM session_products WHERE session_id=? AND onliner_id='' "
            "GROUP BY category_key ORDER BY category_key",
            (session_id,),
        ),
        "duplicate_ids": (
            "SELECT onliner_id,COUNT(*) FROM session_products "
            "WHERE session_id=? AND onliner_id<>'' "
            "GROUP BY onliner_id HAVING COUNT(*)>1",
            (session_id,),
        ),
        "fts_search": (
            "SELECT row_index FROM session_products_fts WHERE session_id=? AND session_products_fts MATCH ? LIMIT 100",
            (session_id, "lenovo"),
        ),
    }
    return {
        "session": {
            "session_id": session_id,
            "row_count": int(latest["row_count"]),
            "revision": int(latest["revision"]),
        },
        "plans": {name: _explain(connection, sql, params) for name, (sql, params) in queries.items()},
    }


def _profile_catalog(connection):
    catalog_count = int(connection.execute("SELECT COUNT(*) FROM onliner_catalog").fetchone()[0])
    name_count = int(connection.execute("SELECT COUNT(*) FROM name_index").fetchone()[0])
    sample = connection.execute("SELECT onliner_id FROM onliner_catalog LIMIT 1").fetchone()
    sample_id = str(sample["onliner_id"]) if sample else ""
    queries = {
        "exact_id": (
            "SELECT * FROM onliner_catalog WHERE onliner_id=?",
            (sample_id,),
        ),
        "fts_candidates": (
            "SELECT f.onliner_id,f.raw_name,oc.url "
            "FROM name_index_fts f "
            "LEFT JOIN onliner_catalog oc ON oc.onliner_id=f.onliner_id "
            "WHERE name_index_fts MATCH ? LIMIT 200",
            ("lenovo",),
        ),
        "fallback_like": (
            "SELECT ni.onliner_id,ni.raw_name,oc.url "
            "FROM name_index ni JOIN onliner_catalog oc "
            "ON oc.onliner_id=ni.onliner_id "
            "WHERE ni.raw_name LIKE ? LIMIT 200",
            ("%lenovo%",),
        ),
    }
    return {
        "catalog": {
            "products": catalog_count,
            "name_variants": name_count,
        },
        "plans": {name: _explain(connection, sql, params) for name, (sql, params) in queries.items()},
    }


def _explain(connection, sql, params):
    rows = connection.execute(
        f"EXPLAIN QUERY PLAN {sql}",
        params,
    ).fetchall()
    details = [str(row["detail"]) for row in rows]
    return {
        "details": details,
        "uses_index": any("USING INDEX" in detail or "USING COVERING INDEX" in detail for detail in details),
        "temporary_btree": any("USE TEMP B-TREE" in detail for detail in details),
        "full_scan": any(detail.startswith("SCAN ") and "VIRTUAL TABLE" not in detail for detail in details),
    }


def build_report(*, catalog_db, session_db):
    return {
        "schema": "price-mixer-sqlite-profile-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "databases": [
            profile_database(catalog_db, kind="catalog"),
            profile_database(session_db, kind="session"),
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-db", required=True)
    parser.add_argument("--session-db", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    report = build_report(
        catalog_db=args.catalog_db,
        session_db=args.session_db,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 1 if any(item["status"] == "error" for item in report["databases"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
