"""Tests for isolated API validation worker orchestration."""

import threading

import pandas as pd

from price_mixer.services.id_validation import ValidationCancelledError
from price_mixer.services.id_validation_api_worker import run_api_validation_worker


class _AnalysisRunner:
    def __init__(self, result):
        self.result = result

    def run(self, _session_dir, _payload, progress_update=None):
        if progress_update:
            progress_update({"running": True, "done": 2, "total": 2})
        return self.result


def _dependencies(initial_df, current_df):
    reads = [initial_df.copy(), current_df.copy()]
    saved = {}
    statuses = []
    analysis = {
        "results": [
            {
                "row_idx": 10,
                "name": "Wrong A",
                "onliner_id": "1",
                "mutate_df_clear": True,
            },
            {
                "row_idx": 20,
                "name": "Wrong B",
                "onliner_id": "2",
                "mutate_df_clear": True,
            },
        ],
        "candidate_map": {"Wrong A": [], "Wrong B": []},
        "errors": 0,
    }

    def apply_api_result(
        frame,
        result,
        _name_key,
        _bindings,
        _confirmed_rows,
        _skipped_rows,
        cleared_items,
        journal_changes,
        **kwargs,
    ):
        frame.at[result["row_idx"], "OnlinerID"] = kwargs["clear_value"]
        cleared_items.append({"name": result["name"]})
        journal_changes.append({"row_idx": result["row_idx"]})
        return {"confirmed": 0, "skipped_api": 0}

    def save_results(**kwargs):
        saved.update(kwargs)

    deps = {
        "mutation_lock": threading.RLock(),
        "read_consolidated_df": lambda _session_dir: reads.pop(0),
        "ensure_category_column": lambda value: value,
        "load_manual_id_bindings": lambda: {},
        "load_review_queue": lambda: {},
        "collect_tasks": lambda frame, **_kwargs: (
            [(idx, row.copy()) for idx, row in frame.iterrows()],
            0,
        ),
        "is_tgpc_pc_name": lambda _name: False,
        "load_app_settings": lambda: {"no_id_search": {"max_candidates": 10}},
        "normalize_onliner_id": lambda value: str(value).strip(),
        "is_manually_confirmed_id": lambda *_args, **_kwargs: False,
        "normalize_name_key": lambda name: name.casefold(),
        "build_no_column_state": lambda: {"running": False, "message": "no column"},
        "build_prepare_state": lambda mode, total: {
            "running": True,
            "mode": mode,
            "total": total,
        },
        "build_no_tasks_state": lambda mode: {"running": False, "mode": mode},
        "analysis_runner": _AnalysisRunner(analysis),
        "product_cache_ttl": 60,
        "get_max_workers": lambda default=8: default,
        "progress_update": statuses.append,
        "raise_if_cancelled": lambda: None,
        "cancel_requested": lambda: False,
        "apply_api_result": apply_api_result,
        "clear_value": pd.NA,
        "populate_review_queue": lambda cleared, *_args, **_kwargs: len(cleared),
        "save_results": save_results,
        "save_manual_id_bindings": lambda _payload: None,
        "save_review_queue": lambda _payload: None,
        "append_id_change_journal": lambda _payload: None,
        "write_consolidated_df": lambda *_args: None,
        "write_consolidated_json": lambda *_args: None,
        "build_finish_state": lambda **kwargs: {
            "running": False,
            "done": kwargs["total"],
            "cleared": len(kwargs["cleared_items"]),
            "skipped_api": kwargs["skipped"],
            "errors": kwargs["errors"],
        },
        "cancelled_error": ValidationCancelledError,
        "build_cancelled_state": lambda mode: {
            "running": False,
            "cancelled": True,
            "mode": mode,
        },
        "build_error_state": lambda mode, exc: {
            "running": False,
            "mode": mode,
            "message": str(exc),
        },
    }
    return deps, saved, statuses


def test_api_worker_commits_only_unchanged_rows(tmp_path):
    initial_df = pd.DataFrame(
        {
            "Название": ["Wrong A", "Wrong B"],
            "OnlinerID": ["1", "2"],
            "Поставщик": ["S", "S"],
        },
        index=[10, 20],
    )
    current_df = initial_df.copy()
    current_df.at[20, "OnlinerID"] = "999"
    deps, saved, statuses = _dependencies(initial_df, current_df)

    run_api_validation_worker(tmp_path, deps)

    assert saved["mode"] == "api"
    assert pd.isna(saved["df"].at[10, "OnlinerID"])
    assert saved["df"].at[20, "OnlinerID"] == "999"
    assert statuses[-1] == {
        "running": False,
        "done": 2,
        "cleared": 1,
        "skipped_api": 1,
        "errors": 0,
    }


def test_api_worker_reports_cancellation_without_saving(tmp_path):
    frame = pd.DataFrame(
        {"Название": ["SSD"], "OnlinerID": ["111"], "Поставщик": ["A"]},
        index=[10],
    )
    deps, saved, statuses = _dependencies(frame, frame)

    class CancelledRunner:
        def run(self, *_args, **_kwargs):
            raise ValidationCancelledError("cancelled")

    deps["analysis_runner"] = CancelledRunner()

    run_api_validation_worker(tmp_path, deps)

    assert saved == {}
    assert statuses[-1] == {
        "running": False,
        "cancelled": True,
        "mode": "api",
    }
