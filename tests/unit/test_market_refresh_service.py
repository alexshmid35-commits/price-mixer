import threading
import time

import pandas as pd

from price_mixer.services import market_refresh as svc


def test_start_market_refresh_validates_session_and_uses_worker(tmp_path):
    status = svc.make_market_refresh_status()
    calls = []

    assert svc.start_market_refresh("", [], worker=lambda *_: None, status=status) == {
        "status": "error",
        "message": "No session",
    }
    assert svc.start_market_refresh(str(tmp_path), [], worker=lambda *_: None, status=status) == {
        "status": "error",
        "message": "No data",
    }

    (tmp_path / "consolidated.json").write_text("{}", encoding="utf-8")

    class SyncThread:
        def __init__(self, target, args=(), daemon=False):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            calls.append((self.args, self.daemon))
            self.target(*self.args)

    result = svc.start_market_refresh(
        str(tmp_path),
        ["CPU"],
        worker=lambda session_dir, categories: status.update({"running": False, "worker_categories": categories}),
        status=status,
        lock=threading.RLock(),
        thread_factory=SyncThread,
        now_fn=lambda: 100,
    )

    assert result == {"status": "started"}
    assert calls == [((str(tmp_path), ["CPU"]), True)]
    assert status["started_at"] == 100
    assert status["worker_categories"] == ["CPU"]


def test_start_market_refresh_blocks_when_already_running(tmp_path):
    (tmp_path / "consolidated_price.xlsx").write_text("placeholder", encoding="utf-8")
    status = svc.make_market_refresh_status()
    status["running"] = True

    result = svc.start_market_refresh(str(tmp_path), [], worker=lambda *_: None, status=status)

    assert result == {"status": "already_running"}


def test_collect_known_onliner_ids_deduplicates_sources(tmp_path):
    (tmp_path / "consolidated_price.xlsx").write_text("placeholder", encoding="utf-8")

    def read_df(_session_dir):
        return pd.DataFrame([
            {"OnlinerID": "1.0"},
            {"OnlinerID": "2"},
            {"OnlinerID": ""},
        ])

    ids = svc.collect_known_onliner_ids(
        max_ids=4,
        session_dir=str(tmp_path),
        read_consolidated_df=read_df,
        load_market_cache=lambda: {"2": {}, "3": {}},
        load_id_cache=lambda: {"a": {"id": "3"}, "b": {"id": "4"}, "bad": "x"},
    )

    assert ids == ["1", "2", "3", "4"]


def test_market_id_hints_from_session_reads_first_row_per_id(tmp_path):
    (tmp_path / "consolidated_price.xlsx").write_text("placeholder", encoding="utf-8")

    def read_df(_session_dir):
        return pd.DataFrame([
            {"OnlinerID": "1", "Название": "First", "Категория": "CPU"},
            {"OnlinerID": "1", "Название": "Second", "Категория": "GPU"},
            {"OnlinerID": "2", "Название": "Third", "Категория": "SSD"},
        ])

    hints = svc.market_id_hints_from_session(
        str(tmp_path),
        read_consolidated_df=read_df,
        ensure_category_column=lambda df: df,
        row_category=lambda row: row.get("Категория", ""),
    )

    assert hints == {
        "1": {"name": "First", "category": "CPU"},
        "2": {"name": "Third", "category": "SSD"},
    }


def test_market_refresh_worker_updates_status_and_cache(tmp_path):
    (tmp_path / "consolidated_price.xlsx").write_text("placeholder", encoding="utf-8")
    status = svc.make_market_refresh_status()
    status["running"] = True
    cache = {"2": {"updated_at": 90, "min": 20, "avg": 20, "max": 20, "offers": 1}}
    saved = []
    calls = []

    def read_df(_session_dir):
        return pd.DataFrame([
            {"OnlinerID": "1", "Название": "CPU item", "Категория": "CPU"},
            {"OnlinerID": "2", "Название": "GPU item", "Категория": "GPU"},
        ])

    def fetch_stats(oid, product_name="", category_name=""):
        calls.append((oid, product_name, category_name))
        if oid == "1":
            return {"min": 10, "avg": 11, "max": 12, "offers": 2}
        return {"min": None, "avg": None, "max": None, "offers": 0, "_error": True, "_error_reason": "empty"}

    svc.market_refresh_worker(
        str(tmp_path),
        ["CPU", "GPU"],
        read_consolidated_df=read_df,
        ensure_category_column=lambda df: df,
        row_category=lambda row: row.get("Категория", ""),
        fetch_market_stats=fetch_stats,
        load_cache=lambda: cache,
        save_cache=lambda data: saved.append(dict(data)),
        status=status,
        lock=threading.RLock(),
        max_workers=1,
        now_fn=lambda: 100,
    )

    assert status["running"] is False
    assert status["total"] == 2
    assert status["done"] == 2
    assert status["success"] == 1
    assert status["errors"] == 1
    assert status["categories"]["CPU"]["percent"] == 100
    assert status["categories"]["GPU"]["errors"] == 1
    assert saved[0]["1"]["updated_at"] == 100
    assert saved[0]["1"]["avg"] == 11
    assert saved[0]["2"]["avg"] == 20
    assert calls == [("1", "CPU item", "CPU"), ("2", "GPU item", "GPU")]


def test_market_refresh_worker_closes_idle_hanging_requests(tmp_path):
    (tmp_path / "consolidated_price.xlsx").write_text("placeholder", encoding="utf-8")
    status = svc.make_market_refresh_status()
    status["running"] = True
    saved = []

    def read_df(_session_dir):
        return pd.DataFrame([
            {"OnlinerID": "1", "Название": "Fast item", "Категория": "CPU"},
            {"OnlinerID": "2", "Название": "Slow item", "Категория": "GPU"},
        ])

    def fetch_stats(oid, product_name="", category_name=""):
        if oid == "2":
            time.sleep(0.08)
        return {"min": 10, "avg": 10, "max": 10, "offers": 1}

    svc.market_refresh_worker(
        str(tmp_path),
        ["CPU", "GPU"],
        read_consolidated_df=read_df,
        ensure_category_column=lambda df: df,
        row_category=lambda row: row.get("Категория", ""),
        fetch_market_stats=fetch_stats,
        load_cache=lambda: {},
        save_cache=lambda data: saved.append(dict(data)),
        status=status,
        lock=threading.RLock(),
        max_workers=2,
        idle_timeout_sec=0.01,
        now_fn=lambda: 100,
    )

    assert status["running"] is False
    assert status["phase"] == "finished"
    assert status["done"] == 2
    assert status["success"] == 1
    assert status["errors"] == 1
    assert saved[0]["1"]["avg"] == 10
    assert saved[0]["2"]["_error"] is True
    assert "таймаут обновления цен" in saved[0]["2"]["_error_reason"]


def test_auto_market_refresh_once_skips_disabled_manual_running_and_not_due():
    status = svc.make_market_refresh_status()

    assert svc.auto_market_refresh_once(
        load_settings=lambda: {"enabled": False},
        save_settings=lambda settings: None,
        collect_known_ids=lambda session_dir=None: [],
        get_last_session_dir=lambda: "/tmp/session",
        get_id_hints=lambda session_dir: {},
        fetch_market_stats=lambda oid, **kwargs: {},
    ) == {"status": "disabled"}

    status["running"] = True
    assert svc.auto_market_refresh_once(
        load_settings=lambda: {"enabled": True, "interval_hours": 12, "last_run_ts": 0},
        save_settings=lambda settings: None,
        collect_known_ids=lambda session_dir=None: [],
        get_last_session_dir=lambda: "/tmp/session",
        get_id_hints=lambda session_dir: {},
        fetch_market_stats=lambda oid, **kwargs: {},
        status=status,
        lock=threading.RLock(),
    ) == {"status": "manual_running"}

    status["running"] = False
    assert svc.auto_market_refresh_once(
        load_settings=lambda: {"enabled": True, "interval_hours": 12, "last_run_ts": 100},
        save_settings=lambda settings: None,
        collect_known_ids=lambda session_dir=None: [],
        get_last_session_dir=lambda: "/tmp/session",
        get_id_hints=lambda session_dir: {},
        fetch_market_stats=lambda oid, **kwargs: {},
        status=status,
        lock=threading.RLock(),
        now_fn=lambda: 120,
    ) == {"status": "not_due"}


def test_auto_market_refresh_once_marks_idle_when_no_ids():
    saved = []

    result = svc.auto_market_refresh_once(
        load_settings=lambda: {"enabled": True, "interval_hours": 99, "last_run_ts": 0},
        save_settings=lambda settings: saved.append(dict(settings)),
        collect_known_ids=lambda session_dir=None: [],
        get_last_session_dir=lambda: "/tmp/session",
        get_id_hints=lambda session_dir: {},
        fetch_market_stats=lambda oid, **kwargs: {},
        now_fn=lambda: 500,
    )

    assert result == {"status": "idle", "count": 0}
    assert saved == [{
        "enabled": True,
        "interval_hours": 99,
        "last_run_ts": 500,
        "last_status": "idle",
        "last_count": 0,
        "last_message": "Нет товаров с OnlinerID для автообновления.",
    }]


def test_auto_market_refresh_once_updates_cache_and_settings():
    settings = {"enabled": True, "interval_hours": 12, "last_run_ts": 0}
    saved_settings = []
    cache = {"2": {"updated_at": 90, "min": 20, "avg": 20, "max": 20, "offers": 1}}
    saved_cache = []
    fetch_calls = []
    times = iter([100, 130])

    def load_settings():
        return dict(settings)

    def save_settings(payload):
        settings.clear()
        settings.update(payload)
        saved_settings.append(dict(payload))

    def fetch_stats(oid, product_name="", category_name=""):
        fetch_calls.append((oid, product_name, category_name))
        if oid == "1":
            return {"min": 10, "avg": 11, "max": 12, "offers": 3}
        return {"min": None, "avg": None, "max": None, "offers": 0, "_error": True}

    result = svc.auto_market_refresh_once(
        load_settings=load_settings,
        save_settings=save_settings,
        collect_known_ids=lambda session_dir=None: ["1", "2"],
        get_last_session_dir=lambda: "/tmp/session",
        get_id_hints=lambda session_dir: {"1": {"name": "CPU", "category": "Процессор"}},
        fetch_market_stats=fetch_stats,
        load_cache=lambda: cache,
        save_cache=lambda payload: saved_cache.append(dict(payload)),
        max_workers=1,
        now_fn=lambda: next(times),
    )

    assert result == {"status": "ok", "count": 2}
    assert fetch_calls == [("1", "CPU", "Процессор"), ("2", "", "")]
    assert saved_settings[0]["last_status"] == "running"
    assert saved_settings[-1]["last_status"] == "ok"
    assert saved_settings[-1]["last_run_ts"] == 130
    assert saved_settings[-1]["last_count"] == 2
    assert saved_cache[0]["1"]["updated_at"] == 100
    assert saved_cache[0]["1"]["avg"] == 11
    assert saved_cache[0]["2"]["avg"] == 20


def test_auto_market_refresh_once_records_error_status():
    settings = {"enabled": True, "interval_hours": 12, "last_run_ts": 0}
    saved = []

    def save_settings(payload):
        settings.clear()
        settings.update(payload)
        saved.append(dict(payload))

    result = svc.auto_market_refresh_once(
        load_settings=lambda: dict(settings),
        save_settings=save_settings,
        collect_known_ids=lambda session_dir=None: (_ for _ in ()).throw(RuntimeError("boom")),
        get_last_session_dir=lambda: "/tmp/session",
        get_id_hints=lambda session_dir: {},
        fetch_market_stats=lambda oid, **kwargs: {},
        now_fn=lambda: 100,
    )

    assert result == {"status": "error", "message": "boom"}
    assert saved[-1]["last_status"] == "error"
    assert saved[-1]["last_message"] == "Ошибка автообновления: boom"
