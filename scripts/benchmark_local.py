#!/usr/bin/env python3
"""Reproducible local benchmark for consolidated table paging."""

from __future__ import annotations

import argparse
import json
import platform
import resource
import statistics
import subprocess
import sys
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from price_mixer.services.consolidated_paging import (  # noqa: E402
    ConsolidatedPagingCache,
    build_consolidated_page,
)

SUPPLIERS = ("IVEN", "IVEN_zakaz", "Tradex", "N-Tech")
CATEGORIES = ("SSD", "Монитор", "Ноутбук", "ПЭВМ")


def generate_rows(size):
    rows = []
    for index in range(max(0, int(size))):
        rows.append(
            [
                "" if index % 7 == 0 else str(index // 3),
                f"Product Model {index % 13000} Variant {index}",
                float(index % 9000) + 0.25,
                SUPPLIERS[index % len(SUPPLIERS)],
                "12",
                str(1 + index % 3),
                float(index % 9000) + 10.0,
                float(index % 9000) + 15.0,
                index,
                CATEGORIES[index % len(CATEGORIES)],
            ]
        )
    return rows


def benchmark_size(size, *, repeats=12):
    cpu_started = time.process_time()
    rss_before_kb = _max_rss_kb()
    tracemalloc.start()
    rows = generate_rows(size)
    order = [(1, "asc")]
    started = time.perf_counter()
    uncached = build_consolidated_page(
        rows,
        start=0,
        length=100,
        order_specs=order,
    )
    uncached_ms = _elapsed_ms(started)

    cache = ConsolidatedPagingCache()
    started = time.perf_counter()
    cold = cache.build_page(
        ("synthetic", size),
        rows,
        start=0,
        length=100,
        order_specs=order,
    )
    cold_ms = _elapsed_ms(started)

    warm_page = []
    for iteration in range(max(3, int(repeats))):
        started = time.perf_counter()
        cache.build_page(
            ("synthetic", size),
            rows,
            start=(iteration % 8) * 100,
            length=100,
            order_specs=order,
        )
        warm_page.append(_elapsed_ms(started))

    started = time.perf_counter()
    cache.build_page(
        ("synthetic", size),
        rows,
        start=0,
        length=100,
        search="model 42",
        order_specs=order,
    )
    search_cold_ms = _elapsed_ms(started)

    warm_search = []
    for _iteration in range(max(3, int(repeats))):
        started = time.perf_counter()
        cache.build_page(
            ("synthetic", size),
            rows,
            start=0,
            length=100,
            search="model 42",
            order_specs=order,
        )
        warm_search.append(_elapsed_ms(started))

    page_payload = json.dumps(
        cold,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    full_payload = json.dumps(
        {"data": rows},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "rows": int(size),
        "cpu_ms": round(
            (time.process_time() - cpu_started) * 1000.0,
            3,
        ),
        "peak_python_bytes": int(peak_bytes),
        "max_rss_delta_kb": max(0, _max_rss_kb() - rss_before_kb),
        "uncached_page_ms": round(uncached_ms, 3),
        "cold_cached_page_ms": round(cold_ms, 3),
        "warm_page_p50_ms": round(statistics.median(warm_page), 3),
        "warm_page_p95_ms": round(_percentile(warm_page, 95), 3),
        "cold_search_ms": round(search_cold_ms, 3),
        "warm_search_p50_ms": round(statistics.median(warm_search), 3),
        "warm_search_p95_ms": round(_percentile(warm_search, 95), 3),
        "page_payload_bytes": len(page_payload),
        "full_payload_bytes": len(full_payload),
        "page_rows": len(cold["data"]),
        "uncached_rows": len(uncached["data"]),
    }


def build_report(sizes, *, repeats=12):
    return {
        "schema": "price-mixer-benchmark-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "results": [benchmark_size(size, repeats=repeats) for size in sizes],
    }


def compare_reports(current, baseline, *, threshold_percent=20.0):
    baseline_by_rows = {int(item["rows"]): item for item in baseline.get("results", [])}
    regressions = []
    for current_item in current.get("results", []):
        rows = int(current_item["rows"])
        previous = baseline_by_rows.get(rows)
        if previous is None:
            continue
        for metric, current_value in current_item.items():
            if not metric.endswith("_ms"):
                continue
            previous_value = float(previous.get(metric, 0) or 0)
            if previous_value <= 0:
                continue
            increase = (float(current_value) - previous_value) / previous_value * 100.0
            if increase > float(threshold_percent):
                regressions.append(
                    {
                        "rows": rows,
                        "metric": metric,
                        "baseline": previous_value,
                        "current": float(current_value),
                        "increase_percent": round(increase, 2),
                    }
                )
    return regressions


def _percentile(values, percentile):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * float(percentile) / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _elapsed_ms(started):
    return (time.perf_counter() - started) * 1000.0


def _max_rss_kb():
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return value // 1024
    return value


def _git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _parser():
    parser = argparse.ArgumentParser(
        description="Benchmark Price Mixer table paging without external APIs",
    )
    parser.add_argument(
        "--sizes",
        default="5000,25000,100000",
        help="Comma-separated row counts",
    )
    parser.add_argument("--repeats", type=int, default=12)
    parser.add_argument("--output")
    parser.add_argument("--baseline")
    parser.add_argument("--threshold-percent", type=float, default=20.0)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    sizes = [int(value) for value in str(args.sizes).split(",") if str(value).strip()]
    report = build_report(sizes, repeats=args.repeats)
    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        report["regressions"] = compare_reports(
            report,
            baseline,
            threshold_percent=args.threshold_percent,
        )
    payload = json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 1 if report.get("regressions") else 0


if __name__ == "__main__":
    raise SystemExit(main())
