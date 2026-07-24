#!/usr/bin/env python3
"""Benchmark the indexed session-products store without external services."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from price_mixer.services.session_products import SessionProductStore  # noqa: E402
from scripts.benchmark_local import generate_rows  # noqa: E402


def _elapsed_ms(started):
    return (time.perf_counter() - started) * 1000


def _percentile(values, percentile):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * float(percentile) / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def benchmark_size(size, repeats=12):
    rows = generate_rows(size)
    with tempfile.TemporaryDirectory(prefix="price-mixer-session-bench-") as temp:
        database = Path(temp) / "session_products.db"
        session = Path(temp) / "benchmark-session"
        store = SessionProductStore(database, mode="canonical")
        started = time.perf_counter()
        store.replace_rows(session, rows, source_revision=f"rows:{size}")
        sync_ms = _elapsed_ms(started)
        page_times = []
        search_times = []
        for iteration in range(max(3, int(repeats))):
            started = time.perf_counter()
            store.query_page(
                session,
                start=(iteration % 8) * 100,
                length=100,
                order_specs=[(2, "desc")],
            )
            page_times.append(_elapsed_ms(started))
            started = time.perf_counter()
            store.query_page(
                session,
                search=f"model {iteration % 20}",
                length=100,
                order_specs=[(1, "asc")],
            )
            search_times.append(_elapsed_ms(started))
        return {
            "rows": int(size),
            "initial_sync_ms": round(sync_ms, 3),
            "page_p50_ms": round(statistics.median(page_times), 3),
            "page_p95_ms": round(_percentile(page_times, 95), 3),
            "search_p50_ms": round(statistics.median(search_times), 3),
            "search_p95_ms": round(_percentile(search_times, 95), 3),
            "database_bytes": database.stat().st_size,
        }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[5000, 25000, 100000])
    parser.add_argument("--repeats", type=int, default=12)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = {
        "schema": "price-mixer-session-products-benchmark-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "results": [
            benchmark_size(size, repeats=args.repeats)
            for size in args.sizes
        ],
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
