"""Tests for the isolated bulk OnlinerID verification process."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pandas as pd

from price_mixer.services.isolated_verify_job import (
    DurableVerifyStatusWriter,
    IsolatedVerifyJob,
    verify_status_path,
)
from price_mixer.state_store import load_dict, save_json_atomic
from price_mixer.workers import verify_ids


def _session_with_data(tmp_path):
    (tmp_path / "consolidated.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_isolated_job_starts_worker_and_persists_pid(tmp_path):
    calls = []

    def fake_popen(command, **options):
        calls.append((list(command), dict(options)))
        return SimpleNamespace(pid=4321)

    job = IsolatedVerifyJob(popen_factory=fake_popen, process_checker=lambda pid: pid == 4321)
    result = job.start(_session_with_data(tmp_path), {"running": True, "started_at": 100, "items": []})

    assert result == {"status": "started"}
    assert calls[0][0][1:3] == ["-m", "price_mixer.workers.verify_ids"]
    status = job.status(tmp_path)
    assert status["running"] is True
    assert status["state"] == "running"
    assert status["pid"] == 4321
    assert status["job_id"]


def test_isolated_job_rejects_second_start_while_pid_is_alive(tmp_path):
    session_dir = _session_with_data(tmp_path)
    save_json_atomic(verify_status_path(session_dir), {
        "running": True,
        "state": "running",
        "pid": 77,
        "job_id": "active",
        "started_at": 100,
    })
    job = IsolatedVerifyJob(
        popen_factory=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not launch")),
        process_checker=lambda pid: pid == 77,
    )

    assert job.start(session_dir, {"running": True}) == {"status": "already_running"}


def test_isolated_job_marks_dead_worker_as_error(tmp_path):
    session_dir = _session_with_data(tmp_path)
    save_json_atomic(verify_status_path(session_dir), {
        "running": True,
        "state": "running",
        "pid": 88,
        "job_id": "dead",
        "started_at": 100,
        "items": [],
    })
    job = IsolatedVerifyJob(process_checker=lambda _pid: False)

    status = job.status(session_dir)

    assert status["running"] is False
    assert status["state"] == "error"
    assert "аварийно" in status["message"]
    assert load_dict(verify_status_path(session_dir))["state"] == "error"


def test_durable_writer_throttles_progress_but_persists_terminal_state(tmp_path):
    path = verify_status_path(tmp_path)
    save_json_atomic(path, {"job_id": "job-1", "running": True})
    current_time = [10.0]
    writer = DurableVerifyStatusWriter(
        path,
        "job-1",
        pid=55,
        min_interval=0.25,
        clock=lambda: current_time[0],
    )

    assert writer({"running": True, "done": 0, "total": 10}) is True
    current_time[0] = 10.1
    assert writer({"running": True, "done": 1, "total": 10}) is False
    current_time[0] = 10.3
    assert writer({"running": True, "done": 2, "total": 10}) is True
    current_time[0] = 10.31
    assert writer({"running": False, "state": "done", "done": 10, "total": 10}) is True

    status = load_dict(path)
    assert status["state"] == "done"
    assert status["pid"] == 55
    assert status["done"] == 10


def test_worker_entrypoint_bridges_app_status_to_durable_file(tmp_path, monkeypatch):
    status_path = verify_status_path(tmp_path)
    save_json_atomic(status_path, {
        "running": True,
        "state": "starting",
        "job_id": "job-2",
        "items": [],
        "report_items": [],
    })
    fake_app = SimpleNamespace(
        VERIFY_ALL_IDS_LOCK=threading.RLock(),
        VERIFY_ALL_IDS_STATUS_WRITER=None,
        verify_all_ids_status={},
    )

    def fake_worker(_session_dir):
        fake_app.verify_all_ids_status.update({
            "running": False,
            "state": "done",
            "total": 2,
            "done": 2,
            "matched": 2,
            "items": [],
            "report_items": [{"onliner_id": "1"}],
        })
        fake_app.VERIFY_ALL_IDS_STATUS_WRITER(fake_app.verify_all_ids_status, force=True)

    fake_app._verify_all_ids_worker = fake_worker
    monkeypatch.setitem(__import__("sys").modules, "app", fake_app)

    result = verify_ids.main([
        "--session-dir",
        str(tmp_path),
        "--status-file",
        str(status_path),
        "--job-id",
        "job-2",
    ])

    assert result == 0
    status = load_dict(status_path)
    assert status["running"] is False
    assert status["state"] == "done"
    assert status["matched"] == 2
    assert status["report_items"] == [{"onliner_id": "1"}]


def test_real_worker_process_finishes_empty_session(tmp_path):
    (tmp_path / "consolidated.json").write_text('{"data": []}', encoding="utf-8")
    job = IsolatedVerifyJob()

    assert job.start(tmp_path, {
        "running": True,
        "state": "starting",
        "started_at": int(time.time()),
        "items": [],
        "report_items": [],
    }) == {"status": "started"}

    deadline = time.monotonic() + 30
    status = job.status(tmp_path)
    while status.get("running") and time.monotonic() < deadline:
        time.sleep(0.1)
        status = job.status(tmp_path)

    assert status["running"] is False
    assert status["state"] == "done"
    assert status["total"] == 0


def test_app_validation_runtime_uses_isolated_verify_callbacks(tmp_path, monkeypatch):
    import app as app_module

    calls = []

    class FakeJob:
        def start(self, session_dir, initial_state):
            calls.append(("start", session_dir, dict(initial_state)))
            return {"status": "started"}

        def status(self, session_dir, fallback=None):
            calls.append(("status", session_dir, dict(fallback or {})))
            return {"running": True, "state": "running", "items": []}

    monkeypatch.setattr(app_module, "VERIFY_ALL_IDS_JOB", FakeJob())
    monkeypatch.setattr(app_module, "get_active_session_dir", lambda: str(tmp_path))

    assert app_module._verify_all_ids_start_payload() == {"status": "started"}
    assert app_module._verify_all_ids_status_payload()["state"] == "running"
    assert calls[0][0:2] == ("start", str(tmp_path))
    assert calls[0][2]["running"] is True
    assert calls[1][0:2] == ("status", str(tmp_path))


def test_app_verify_worker_loads_shared_snapshots_once(tmp_path, monkeypatch):
    import app as app_module

    df = pd.DataFrame({
        "OnlinerID": ["1", "2"],
        "Название": ["A", "B"],
        "Поставщик": ["S", "S"],
        "Категория": ["C", "C"],
    })
    loads = {"settings": 0, "cache": 0, "bindings": 0}

    def load_once(name, value):
        loads[name] += 1
        return value

    monkeypatch.setattr(app_module, "read_consolidated_json_fast_df", lambda _path: df.copy())
    monkeypatch.setattr(app_module, "ensure_category_column", lambda value: value)
    monkeypatch.setattr(app_module, "apply_visibility_filter", lambda value, _path: value)
    monkeypatch.setattr(app_module, "_is_tgpc_pc_name", lambda _name: False)
    monkeypatch.setattr(app_module, "load_app_settings", lambda: load_once("settings", {}))
    monkeypatch.setattr(app_module, "load_onliner_product_cache", lambda: load_once("cache", {}))
    monkeypatch.setattr(app_module, "load_manual_id_bindings", lambda: load_once("bindings", {}))
    monkeypatch.setattr(app_module, "get_onliner_api_max_workers", lambda default=8: 2)
    monkeypatch.setattr(
        app_module,
        "_verify_all_ids_one",
        lambda row_idx, row, *_snapshots: {
            "row_idx": row_idx,
            "name": row["Название"],
            "score": 1.0,
            "status": "match",
            "needs_review": False,
        },
    )
    monkeypatch.setattr(app_module, "VERIFY_ALL_IDS_STATUS_WRITER", None)
    with app_module.VERIFY_ALL_IDS_LOCK:
        app_module.verify_all_ids_status.clear()
        app_module.verify_all_ids_status.update({"running": True, "done": 0})

    app_module._verify_all_ids_worker(str(tmp_path))

    assert loads == {"settings": 1, "cache": 1, "bindings": 1}
    assert app_module.verify_all_ids_status["state"] == "done"
    assert app_module.verify_all_ids_status["done"] == 2
    assert app_module.verify_all_ids_status["matched"] == 2


def test_app_verify_worker_fetches_duplicate_id_once(monkeypatch):
    import app as app_module

    fetch_calls = []

    def fake_fetch(onliner_id, **_kwargs):
        fetch_calls.append(onliner_id)
        time.sleep(0.05)
        return {"name": "Same product", "url": "https://example.test/1", "source": "api"}

    monkeypatch.setattr(app_module, "fetch_onliner_product_info", fake_fetch)
    monkeypatch.setattr(
        app_module,
        "calc_name_match",
        lambda _local, _remote: {"score": 1.0, "match": True, "reason": "model_token"},
    )
    shared_results = {}
    shared_events = {}
    shared_lock = threading.Lock()
    rows = [
        pd.Series({"OnlinerID": "123", "Название": "Local A", "Поставщик": "S", "Категория": "C"}),
        pd.Series({"OnlinerID": "123", "Название": "Local B", "Поставщик": "S", "Категория": "C"}),
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                app_module._verify_all_ids_one,
                index,
                row,
                {"verify_id": {"force_refresh_api": True}},
                {},
                {},
                shared_results,
                shared_events,
                shared_lock,
            )
            for index, row in enumerate(rows)
        ]
        results = [future.result() for future in futures]

    assert fetch_calls == ["123"]
    assert [item["status"] for item in results] == ["match", "match"]
