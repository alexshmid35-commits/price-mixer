"""Tests for the reproducible local performance benchmark."""

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "benchmark_local.py"
SPEC = importlib.util.spec_from_file_location("benchmark_local", SCRIPT)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def test_benchmark_size_reports_bounded_page_and_payload_reduction():
    result = benchmark.benchmark_size(500, repeats=3)

    assert result["rows"] == 500
    assert result["page_rows"] == 100
    assert result["uncached_rows"] == 100
    assert result["page_payload_bytes"] < result["full_payload_bytes"]
    assert result["warm_page_p95_ms"] >= 0


def test_compare_reports_flags_only_timing_regression_above_threshold():
    baseline = {
        "results": [{
            "rows": 500,
            "warm_page_p95_ms": 10,
            "page_payload_bytes": 100,
        }],
    }
    current = {
        "results": [{
            "rows": 500,
            "warm_page_p95_ms": 13,
            "page_payload_bytes": 1000,
        }],
    }

    regressions = benchmark.compare_reports(
        current,
        baseline,
        threshold_percent=20,
    )

    assert regressions == [{
        "rows": 500,
        "metric": "warm_page_p95_ms",
        "baseline": 10.0,
        "current": 13.0,
        "increase_percent": 30.0,
    }]
