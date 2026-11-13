import sqlite3
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

import pytest

from price_mixer.services.catalog_refresh import CatalogRefreshState, WEEK, RETRY_DELAY, LEASE_SECONDS
from price_mixer.services.catalog_refresh import last_import_summary


@pytest.fixture
def state(tmp_path):
    path = tmp_path / "refresh.db"

    @contextmanager
    def connection():
        with sqlite3.connect(path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            yield conn

    return CatalogRefreshState(connection)


def test_weekly_success_survives_service_restart(state):
    now = 10 * WEEK
    token, reason = state.claim("sheet:All_Catalog", automatic=True, now=now)
    assert token and reason == "started"
    state.finish(token, success=True, status={"running": False, "finished_at": now}, now=now)
    restarted = CatalogRefreshState(state.connection)
    assert restarted.claim("sheet:All_Catalog", automatic=True, now=now + WEEK - 1) == (None, "fresh")
    assert restarted.claim("sheet:All_Catalog", automatic=True, now=now + WEEK)[0]


def test_failed_import_retries_later_not_next_week(state):
    now = 10 * WEEK
    token, _ = state.claim("sheet", automatic=True, now=now)
    state.finish(token, success=False, status={"running": False}, now=now)
    assert state.claim("sheet", automatic=True, now=now + RETRY_DELAY - 1) == (None, "retry_later")
    assert state.claim("sheet", automatic=True, now=now + RETRY_DELAY)[0]


def test_manual_import_bypasses_interval_but_not_shared_lease(state):
    now = 10 * WEEK
    token, _ = state.claim("sheet", automatic=True, now=now)
    assert state.claim("sheet", now=now) == (None, "already_running")
    state.finish(token, success=True, status={"running": False}, now=now)
    assert state.claim("sheet", now=now + 1)[0]


def test_new_source_is_not_delayed_by_other_sheet(state):
    now = 10 * WEEK
    token, _ = state.claim("sheet:A", now=now)
    state.finish(token, success=True, status={"running": False}, now=now)
    assert state.claim("sheet:B", automatic=True, now=now + 1)[0]


def test_crashed_import_lease_expires_and_old_owner_cannot_release_new_import(state):
    now = 10 * WEEK
    first, _ = state.claim("sheet", now=now)
    second, _ = state.claim("sheet", now=now + LEASE_SECONDS)
    assert first != second
    state.finish(first, success=True, status={"running": False}, now=now + LEASE_SECONDS)
    assert state.claim("sheet", now=now + LEASE_SECONDS) == (None, "already_running")


def test_concurrent_connections_start_only_one_import(state):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: state.claim("sheet", now=10 * WEEK), range(6)))
    assert sum(token is not None for token, _ in results) == 1


def test_remote_process_can_read_completion(state):
    now = 10 * WEEK
    token, _ = state.claim("sheet", now=now)
    other = CatalogRefreshState(state.connection)
    assert other.status(now=now)["running"] is True
    state.finish(token, success=True, status={"running": False, "finished_at": now, "inserted": 12}, now=now)
    assert other.status(now=now)["inserted"] == 12
    with state.connection() as conn:
        assert last_import_summary(conn) == {'finished_at': now, 'inserted': 12, 'updated': None}
    token, _ = state.claim('sheet', now=now + 1)
    state.finish(token, success=False, status={'running': False, 'finished_at': now + 1, 'inserted': 99}, now=now + 1)
    with state.connection() as conn:
        assert last_import_summary(conn) == {'finished_at': now, 'inserted': None, 'updated': None}


def test_processing_trigger_uses_import_sheet_not_export_tab(monkeypatch):
    import app
    calls = []
    monkeypatch.setattr(app, "load_app_settings", lambda: {
        "onliner_db_import": {"google_sheet_id": "catalog", "google_sheet_name": "All_Catalog"},
        "export": {"google_sheets_spreadsheet_url_or_id": "other", "google_sheets_tab": "Price"},
    })
    monkeypatch.setattr(app, "_onliner_db_import_gsheet", lambda payload, **kwargs: calls.append((payload, kwargs)))
    app._maybe_refresh_catalog_after_processing()
    assert calls[0][0] == {"sheet_id": "catalog", "sheet_name": "All_Catalog", "force_refresh": True}
    assert calls[0][1]["automatic"] is True


def test_no_import_when_source_not_configured(monkeypatch):
    import app
    monkeypatch.setattr(app, "load_app_settings", lambda: {})
    monkeypatch.setattr(app, "_onliner_db_import_gsheet", lambda *args, **kwargs: pytest.fail("unexpected import"))
    assert app._maybe_refresh_catalog_after_processing()["status"] == "not_configured"


@pytest.mark.parametrize("fails", [False, True])
def test_processing_hook_is_only_after_success_and_refresh_error_does_not_break_price(monkeypatch, fails):
    import app
    calls = []
    result = {"session_id": "working"}
    def process(*args, **kwargs):
        calls.append("processed")
        if fails:
            raise ValueError("bad price")
        return result
    def refresh():
        calls.append("refresh")
        raise RuntimeError("network unavailable")
    monkeypatch.setattr(app, "_processing_process_supplier_files", process)
    monkeypatch.setattr(app, "_maybe_refresh_catalog_after_processing", refresh)
    if fails:
        with pytest.raises(ValueError):
            app._process_supplier_files([])
        assert calls == ["processed"]
    else:
        assert app._process_supplier_files([]) is result
        assert calls == ["processed", "refresh"]
