#!/usr/bin/env python3
"""Measure local catalog candidate lookup throughput by worker count."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_product_names(session_db, *, limit):
    import sqlite3

    database = Path(session_db).resolve()
    uri = f"file:{database}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=30) as connection:
        rows = connection.execute(
            "SELECT name FROM session_products WHERE onliner_id='' AND name<>'' ORDER BY session_id,row_index LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    names = []
    seen = set()
    for row in rows:
        name = str(row[0] or "").strip()
        key = " ".join(name.casefold().split())
        if name and key and key not in seen:
            seen.add(key)
            names.append(name)
    return names


def benchmark_workers(names, worker_counts, lookup, *, repeats=2):
    results = []
    for workers in worker_counts:
        samples = []
        candidate_counts = []
        for _ in range(max(1, int(repeats))):
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                matches = list(pool.map(lookup, names))
            elapsed = time.perf_counter() - started
            samples.append(elapsed)
            candidate_counts.append(sum(len(items or []) for items in matches))
        median_seconds = statistics.median(samples)
        results.append(
            {
                "workers": int(workers),
                "items": len(names),
                "median_seconds": round(median_seconds, 4),
                "items_per_second": round(
                    len(names) / median_seconds if median_seconds > 0 else 0.0,
                    2,
                ),
                "candidate_count": int(statistics.median(candidate_counts)),
            }
        )
    fastest = max(results, key=lambda item: item["items_per_second"])
    return results, int(fastest["workers"])


def build_report(*, catalog_db, session_db, limit=120, repeats=2):
    catalog_path = Path(catalog_db).resolve()
    os.environ["PRICE_MIXER_DATA_DIR"] = str(catalog_path.parent)
    import app as app_module
    from price_mixer.services import onliner_db

    onliner_db.ONLINER_DB_FILE = catalog_path
    names = load_product_names(session_db, limit=limit)

    def lookup(name):
        return app_module.db_find_top_candidates(
            name,
            top_n=5,
            min_score=0.40,
            allow_b2b=False,
        )

    results, recommended = benchmark_workers(
        names,
        (1, 4, 8, 12),
        lookup,
        repeats=repeats,
    )
    return {
        "schema": "price-mixer-matching-workers-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "catalog_db": str(Path(catalog_db).resolve()),
        "session_db": str(Path(session_db).resolve()),
        "sample_items": len(names),
        "results": results,
        "recommended_workers": recommended,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-db", required=True)
    parser.add_argument("--session-db", required=True)
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    report = build_report(
        catalog_db=args.catalog_db,
        session_db=args.session_db,
        limit=args.limit,
        repeats=args.repeats,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["sample_items"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
