"""Tests for the isolated network phase of the visible ID validation."""

import sys
import threading
from types import SimpleNamespace

import numpy as np
import pandas as pd

from price_mixer.services.id_validation import ValidationCancelledError
from price_mixer.services.validate_clean_analysis import ValidateCleanAnalysisRunner
from price_mixer.state_store import load_dict, save_json_atomic
from price_mixer.workers import validate_clean_analysis as worker_module


def test_analysis_runner_launches_process_and_returns_result(tmp_path):
    calls = []

    class FakeProcess:
        pid = 12
        returncode = 0

        def poll(self):
            return 0

    def fake_popen(command, **options):
        calls.append((list(command), dict(options)))
        result_path = command[command.index("--result") + 1]
        status_path = command[command.index("--status") + 1]
        job_id = command[command.index("--job-id") + 1]
        save_json_atomic(status_path, {"job_id": job_id, "running": True, "done": 1, "total": 1})
        save_json_atomic(result_path, {"job_id": job_id, "results": [{"row_idx": 1}], "errors": 0})
        return FakeProcess()

    runner = ValidateCleanAnalysisRunner(popen_factory=fake_popen)
    progress = []
    result = runner.run(tmp_path, {"tasks": [{"row_idx": 1}]}, progress_update=progress.append)

    assert calls[0][0][1:3] == ["-m", "price_mixer.workers.validate_clean_analysis"]
    assert result["results"] == [{"row_idx": 1}]
    assert progress[-1]["done"] == 1
    assert list(tmp_path.glob(".validate-clean-*.input.json")) == []
    assert list(tmp_path.glob(".validate-clean-*.result.json")) == []


def test_analysis_runner_cancels_active_process_and_cleans_job_files(tmp_path):
    process_started = threading.Event()
    process_stopped = threading.Event()
    errors = []

    class FakeProcess:
        pid = 12
        returncode = None

        def poll(self):
            return -15 if process_stopped.is_set() else None

        def terminate(self):
            self.returncode = -15
            process_stopped.set()

        def wait(self, timeout=None):
            process_stopped.wait(timeout)
            return self.returncode

        def kill(self):
            self.terminate()

    def fake_popen(_command, **_options):
        process_started.set()
        return FakeProcess()

    runner = ValidateCleanAnalysisRunner(popen_factory=fake_popen, poll_interval=0.01)

    def run_job():
        try:
            runner.run(tmp_path, {"tasks": [{"row_idx": 1}]})
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=run_job)
    thread.start()
    assert process_started.wait(1)

    assert runner.cancel(tmp_path) is True
    thread.join(2)

    assert thread.is_alive() is False
    assert len(errors) == 1
    assert isinstance(errors[0], ValidationCancelledError)
    assert list(tmp_path.glob(".validate-clean-*.input.json")) == []
    assert list(tmp_path.glob(".validate-clean-*.result.json")) == []


def test_real_analysis_process_returns_manual_confirmation(tmp_path):
    runner = ValidateCleanAnalysisRunner()

    result = runner.run(tmp_path, {
        "tasks": [{
            "row_idx": 7,
            "name": "Manual product",
            "onliner_id": "123",
            "supplier": "S",
            "manual_confirmed": True,
        }],
        "max_workers": 1,
        "product_cache_ttl": 0,
        "limit_candidates": 10,
    })

    assert result["errors"] == 0
    assert result["results"][0]["row_idx"] == 7
    assert result["results"][0]["record_confirm"] is True
    assert result["results"][0]["reason"] == "manual_confirmed"


def test_analysis_worker_checks_rows_and_prefetches_candidates(tmp_path, monkeypatch):
    fake_app = SimpleNamespace(
        load_onliner_product_cache=lambda: {},
        calc_name_match=lambda local, remote: {
            "score": 1.0 if local == remote else 0.1,
            "reason": "model_token" if local == remote else "different",
        },
        search_onliner_candidates=lambda name, **_kwargs: [{"id": "999", "name": name + " candidate", "score": 0.9}],
    )
    monkeypatch.setitem(sys.modules, "app", fake_app)
    monkeypatch.setattr(
        worker_module,
        "_fetch_product_name",
        lambda oid, hard_timeout=9: {
            "1": ("Good", "u1", "ok"),
            "2": ("Other", "u2", "ok"),
            "3": ("", "", "error"),
        }[oid],
    )
    payload = {
        "tasks": [
            {"row_idx": 1, "name": "Good", "onliner_id": "1", "supplier": "S"},
            {"row_idx": 2, "name": "Wrong", "onliner_id": "2", "supplier": "S"},
            {"row_idx": 3, "name": "Offline", "onliner_id": "3", "supplier": "S"},
        ],
        "max_workers": 3,
        "product_cache_ttl": 0,
        "clear_threshold": 0.65,
        "limit_candidates": 10,
    }
    status_path = tmp_path / "status.json"

    result = worker_module.run_analysis(payload, status_path, "job")

    by_id = {item["onliner_id"]: item for item in result["results"]}
    assert by_id["1"]["record_confirm"] is True
    assert by_id["2"]["mutate_df_clear"] is True
    assert by_id["3"]["mutate_df_clear"] is False
    assert result["candidate_map"]["Wrong"][0]["id"] == "999"
    assert load_dict(status_path)["done"] == 3


def test_app_apply_phase_skips_rows_changed_during_analysis(tmp_path, monkeypatch):
    import app as app_module

    initial_df = pd.DataFrame({
        "OnlinerID": ["1", "2"],
        "Название": ["Wrong A", "Wrong B"],
        "Поставщик": ["S", "S"],
        "Категория": ["C", "C"],
        "Ссылка": ["u1", "u2"],
    }, index=[10, 20])
    current_df = initial_df.copy()
    current_df.at[20, "OnlinerID"] = "999"
    reads = [initial_df, current_df]
    saved = {}
    lock_was_free = []

    class FakeRunner:
        def run(self, _session_dir, _payload, progress_update=None):
            def try_lock():
                acquired = app_module.PRICE_DATA_MUTATION_LOCK.acquire(timeout=1)
                lock_was_free.append(acquired)
                if acquired:
                    app_module.PRICE_DATA_MUTATION_LOCK.release()

            thread = threading.Thread(target=try_lock)
            thread.start()
            thread.join()
            if progress_update:
                progress_update({"running": True, "done": 2, "total": 2})
            return {
                "results": [
                    {
                        "row_idx": 10,
                        "name": "Wrong A",
                        "onliner_id": "1",
                        "api_name": "Other A",
                        "api_url": "",
                        "score": 0.1,
                        "reason": "different",
                        "record_confirm": False,
                        "mutate_df_clear": True,
                    },
                    {
                        "row_idx": 20,
                        "name": "Wrong B",
                        "onliner_id": "2",
                        "api_name": "Other B",
                        "api_url": "",
                        "score": 0.1,
                        "reason": "different",
                        "record_confirm": False,
                        "mutate_df_clear": True,
                    },
                ],
                "candidate_map": {"Wrong A": [], "Wrong B": []},
                "errors": 0,
            }

    monkeypatch.setattr(app_module, "VALIDATE_CLEAN_ANALYSIS_RUNNER", FakeRunner())
    monkeypatch.setattr(app_module, "read_consolidated_json_fast_df", lambda _path: reads.pop(0).copy())
    monkeypatch.setattr(app_module, "ensure_category_column", lambda value: value)
    monkeypatch.setattr(app_module, "_is_tgpc_pc_name", lambda _name: False)
    monkeypatch.setattr(app_module, "load_manual_id_bindings", lambda: {})
    monkeypatch.setattr(app_module, "load_review_queue", lambda: {})
    monkeypatch.setattr(app_module, "load_app_settings", lambda: {"no_id_search": {"max_candidates": 10}})
    monkeypatch.setattr(app_module, "save_manual_id_bindings", lambda payload: saved.setdefault("bindings", payload))
    monkeypatch.setattr(app_module, "save_review_queue", lambda payload: saved.setdefault("queue", payload))
    monkeypatch.setattr(app_module, "append_id_change_journal", lambda payload: saved.setdefault("journal", payload))
    monkeypatch.setattr(app_module, "write_consolidated_json", lambda frame, _path: saved.setdefault("df", frame.copy()))
    monkeypatch.setattr(app_module, "write_consolidated_df_background", lambda *_args, **_kwargs: {"state": "queued"})
    monkeypatch.setattr(app_module, "get_onliner_api_max_workers", lambda default=8: 2)
    monkeypatch.setattr(app_module, "VERIFY_ALL_IDS_STATUS_WRITER", None)
    with app_module.VALIDATE_CLEAN_IDS_LOCK:
        app_module.validate_clean_ids_status.clear()
        app_module.validate_clean_ids_status.update({"running": True})

    app_module._validate_clean_ids_worker(str(tmp_path))

    assert lock_was_free == [True]
    assert np.isnan(saved["df"].at[10, "OnlinerID"])
    assert saved["df"].at[20, "OnlinerID"] == "999"
    assert app_module.validate_clean_ids_status["cleared"] == 1
    assert app_module.validate_clean_ids_status["skipped_api"] == 1
