"""Tests for bulk OnlinerID verification worker orchestration."""

import threading

import pandas as pd

from price_mixer.services.id_validation_verify_worker import run_verify_all_worker


def _dependencies(frame):
    status = {"running": True, "done": 0}
    status_lock = threading.RLock()
    loads = {"settings": 0, "cache": 0, "bindings": 0}

    def status_update(payload):
        with status_lock:
            status.update(payload)

    def load_once(name, value):
        loads[name] += 1
        return value

    deps = {
        "status": status,
        "status_lock": status_lock,
        "status_update": status_update,
        "read_consolidated_df": lambda _session_dir: frame.copy(),
        "ensure_category_column": lambda value: value,
        "apply_visibility_filter": lambda value, _session_dir: value,
        "collect_tasks": lambda value, **_kwargs: (
            [(idx, row.copy()) for idx, row in value.iterrows()],
            0,
        ),
        "is_tgpc_pc_name": lambda _name: False,
        "load_app_settings": lambda: load_once("settings", {}),
        "load_product_cache": lambda: load_once("cache", {}),
        "load_manual_id_bindings": lambda: load_once("bindings", {}),
        "get_max_workers": lambda default=8: default,
        "verify_one": lambda row_idx, row, *_snapshots: {
            "row_idx": row_idx,
            "name": row["Название"],
            "needs_review": row_idx == 20,
        },
        "sort_result_items": lambda items, report: (
            sorted(items, key=lambda item: item["row_idx"]),
            sorted(report, key=lambda item: item["row_idx"]),
        ),
        "clock": lambda: 1234,
    }
    return deps, status, loads


def test_verify_worker_loads_snapshots_once_and_finishes(tmp_path):
    frame = pd.DataFrame(
        {
            "Название": ["Matched", "Review"],
            "OnlinerID": ["1", "2"],
        },
        index=[10, 20],
    )
    deps, status, loads = _dependencies(frame)

    run_verify_all_worker(tmp_path, deps)

    assert loads == {"settings": 1, "cache": 1, "bindings": 1}
    assert status["running"] is False
    assert status["state"] == "done"
    assert status["done"] == 2
    assert status["matched"] == 1
    assert status["mismatched"] == 1
    assert status["errors"] == 0
    assert [item["row_idx"] for item in status["items"]] == [20]
    assert [item["row_idx"] for item in status["report_items"]] == [10, 20]
    assert status["finished_at"] == 1234


def test_verify_worker_reports_read_error(tmp_path):
    frame = pd.DataFrame({"OnlinerID": ["1"]})
    deps, status, loads = _dependencies(frame)
    deps["read_consolidated_df"] = lambda _session_dir: (_ for _ in ()).throw(
        RuntimeError("broken data")
    )

    run_verify_all_worker(tmp_path, deps)

    assert loads == {"settings": 0, "cache": 0, "bindings": 0}
    assert status["running"] is False
    assert status["state"] == "error"
    assert status["finished_at"] == 1234
    assert "broken data" in status["message"]
