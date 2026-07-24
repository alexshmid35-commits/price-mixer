"""Tests for local-database validation worker orchestration."""

import threading

import pandas as pd

from price_mixer.services.id_validation import ValidationCancelledError
from price_mixer.services.id_validation_db_worker import run_db_validation_worker


def _dependencies(tmp_path):
    status = {"running": True}
    saved = {}
    frame = pd.DataFrame({
        "Название": ["SSD"],
        "OnlinerID": ["111"],
        "Поставщик": ["A"],
    })
    state = {
        "confirmed": 1,
        "cleared_items": [],
        "skipped": 0,
        "errors": 0,
        "confirmed_rows": [{"name": "SSD"}],
        "skipped_rows": [],
        "journal_changes": [],
    }
    deps = {
        "status": status,
        "lock": threading.RLock(),
        "read_consolidated_df": lambda _session_dir: frame.copy(),
        "ensure_category_column": lambda value: value,
        "load_manual_id_bindings": lambda: {},
        "load_review_queue": lambda: {},
        "collect_tasks": lambda value, **_kwargs: ([(0, value.iloc[0].copy())], 0),
        "is_tgpc_pc_name": lambda _name: False,
        "build_no_column_state": lambda: {"running": False, "message": "no column"},
        "build_prepare_state": lambda mode, total: {"mode": mode, "total": total},
        "build_no_tasks_state": lambda mode: {"running": False, "mode": mode},
        "run_db_tasks": lambda *_args, **_kwargs: state,
        "is_manually_confirmed_id": lambda *_args, **_kwargs: False,
        "db_get_product_by_id": lambda _oid: None,
        "db_find_exact_id_for_name": lambda _name: None,
        "calc_name_match": lambda *_args: {"score": 1.0},
        "normalize_name_key": lambda name: name,
        "progress_update": lambda _payload: None,
        "log": lambda _message: None,
        "clear_value": pd.NA,
        "cancel_requested": lambda: False,
        "raise_if_cancelled": lambda: None,
        "populate_review_queue": lambda *_args, **_kwargs: 0,
        "db_find_top_candidates": lambda *_args, **_kwargs: [],
        "save_results": lambda **kwargs: saved.update(kwargs),
        "save_manual_id_bindings": lambda _payload: None,
        "save_review_queue": lambda _payload: None,
        "append_id_change_journal": lambda _payload: None,
        "write_consolidated_df": lambda *_args: None,
        "write_consolidated_json": lambda *_args: None,
        "build_finish_state": lambda **kwargs: {"running": False, "done": kwargs["total"], "confirmed": kwargs["confirmed"]},
        "cancelled_error": ValidationCancelledError,
        "build_cancelled_state": lambda mode: {"running": False, "cancelled": True, "mode": mode},
        "build_error_state": lambda mode, exc: {"running": False, "mode": mode, "message": str(exc)},
    }
    return deps, status, saved


def test_db_worker_commits_only_after_success(tmp_path):
    deps, status, saved = _dependencies(tmp_path)

    run_db_validation_worker(tmp_path, deps)

    assert saved["mode"] == "db"
    assert saved["session_dir"] == tmp_path
    assert status["running"] is False
    assert status["done"] == 1
    assert status["confirmed"] == 1


def test_db_worker_reports_cancellation_without_saving(tmp_path):
    deps, status, saved = _dependencies(tmp_path)
    deps["run_db_tasks"] = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        ValidationCancelledError("cancelled")
    )

    run_db_validation_worker(tmp_path, deps)

    assert saved == {}
    assert status["running"] is False
    assert status["cancelled"] is True
    assert status["mode"] == "db"
