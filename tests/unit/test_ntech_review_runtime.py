"""Tests for the N-Tech review queue runtime facade."""

import threading
from types import SimpleNamespace

import pandas as pd

from price_mixer.services.ntech_review_runtime import NTechReviewRuntime


def _runtime(frame, *, session_dir="session"):
    saved = {}
    status = {"running": True}

    def build_row_result(row_idx, row, name, category, now_ts):
        return {
            "action": "queued",
            "name_key": f"ntech::{name.casefold()}",
            "queue_item": {
                "name": name,
                "category": category,
                "supplier": row["Поставщик"],
                "added_at": now_ts,
            },
            "report_item": {"row_idx": int(row_idx), "name": name},
        }

    handler = SimpleNamespace(
        is_target=lambda **_kwargs: True,
        build_row_result=build_row_result,
    )
    runtime = NTechReviewRuntime(
        get_active_session_dir=lambda: session_dir,
        has_consolidated_session_file=lambda _path: True,
        consolidated_json_df=lambda _path, **_kwargs: None,
        read_consolidated_json_fast_df=lambda _path: frame.copy(),
        ensure_category_column=lambda value: value,
        precomputed_row_category=lambda row: row["Категория"],
        row_category=lambda row: row["Категория"],
        get_handler=lambda _mode: handler,
        load_review_queue=lambda: {},
        save_review_queue=lambda queue: saved.update(queue=queue.copy()),
        normalize_catalog_category_name=lambda value: value,
        normalize_onliner_id=lambda value: str(value or "").strip(),
        status=status,
        status_lock=threading.RLock(),
        clock=lambda: 111,
    )
    return runtime, saved, status


def test_ntech_runtime_scans_saves_and_updates_status():
    frame = pd.DataFrame({
        "Название": ["CPU Test"],
        "Поставщик": ["N-Tech"],
        "Категория": ["Процессор"],
        "OnlinerID": [""],
    })
    runtime, saved, status = _runtime(frame)

    payload = runtime.start(
        report_mode="cpu",
        report_title="CPU report",
        handler_mode="cpu",
        success_message=lambda scan: f"queued={scan['queued']}",
        empty_message="empty",
        report_subtitle=lambda scan: f"scanned={scan['scanned']}",
        empty_report_subtitle="empty report",
    )

    assert payload["status"] == "ok"
    assert payload["scanned"] == 1
    assert payload["queued"] == 1
    assert saved["queue"]["ntech::cpu test"]["name"] == "CPU Test"
    assert status["running"] is False
    assert status["total"] == 1
    assert status["done"] == 1
    assert status["report_mode"] == "cpu"
    assert status["started_at"] == 111


def test_ntech_runtime_rejects_missing_session():
    frame = pd.DataFrame()
    runtime, saved, status = _runtime(frame, session_dir=None)

    result = runtime.start(
        report_mode="cpu",
        report_title="CPU report",
        handler_mode="cpu",
        success_message=lambda _scan: "done",
        empty_message="empty",
        report_subtitle=lambda _scan: "report",
        empty_report_subtitle="empty report",
    )

    assert result == (
        {"status": "error", "message": "Нет активной сессии"},
        400,
    )
    assert saved == {}
    assert status == {"running": True}
