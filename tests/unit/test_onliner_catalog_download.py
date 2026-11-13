from io import BytesIO
from urllib.parse import parse_qs, urlparse

import pytest

from price_mixer.services import onliner_db as svc


CORE = b'"Category","Model","onliner_id","Specs"\n"SSD","NV2","12345","Kingston NV2"\n'
FULL = b'Category,Brand,Model,Price,onliner_id,URL,image_url,Specs\nSSD,Kingston,NV2,100,12345,,,Kingston NV2\n'


@pytest.fixture
def download(monkeypatch, tmp_path):
    saved = dict(svc.catalog_import_status)
    svc.catalog_import_status["running"] = False
    monkeypatch.setattr(svc, "ONLINER_DB_GSHEET_CACHE_DIR", tmp_path)
    monkeypatch.setattr(svc, "ONLINER_DB_FILE", tmp_path / "catalog.db")
    imported = []

    def worker(path, ext, **kwargs):
        imported.append((svc._catalog_rows(path, ext), kwargs))
        svc.catalog_import_status["running"] = False

    monkeypatch.setattr(svc, "catalog_import_worker", worker)

    def fetch(force=True, start=lambda target: target()):
        return svc.import_gsheet_payload(
            {"sheet_id": "test-sheet", "sheet_name": "All_Catalog", "force_refresh": force},
            normalize_name_key=lambda name: name.lower(), start_thread=start,
        )

    yield fetch, imported
    svc.catalog_import_status.clear()
    svc.catalog_import_status.update(saved)


def response(body):
    value = BytesIO(body)
    value.headers = {"Content-Length": str(len(body))}
    return value


def test_successful_gsheet_import_updates_weekly_clock_and_preserves_bindings(download, monkeypatch):
    from price_mixer.services.catalog_refresh import CatalogRefreshState, WEEK
    import json
    import time
    fetch, _ = download
    svc.init_onliner_db()
    with svc.db_connection() as conn:
        conn.execute("CREATE TABLE manual_bindings(name_key TEXT PRIMARY KEY, onliner_id TEXT NOT NULL)")
        conn.execute("INSERT INTO manual_bindings(name_key,onliner_id) VALUES ('supplier:my-item','999')")
    monkeypatch.setattr(svc.urllib.request, "urlopen", lambda *_a, **_k: response(CORE))
    monkeypatch.setattr(svc, "catalog_import_worker", lambda path, ext, **kwargs: svc._catalog_import_worker(
        path, ext, normalize_name_key=kwargs['normalize_name_key'], cleanup_file=False))
    assert fetch()["status"] == "started"
    with svc.db_connection() as conn:
        row = conn.execute("SELECT * FROM catalog_refresh_state").fetchone()
        assert row['last_success'] > 0
        assert json.loads(row['status_json'])['percent'] == 100
        assert conn.execute("SELECT onliner_id FROM manual_bindings WHERE name_key='supplier:my-item'").fetchone()[0] == '999'
    state = CatalogRefreshState(svc.db_connection)
    assert state.claim('test-sheet:All_Catalog', automatic=True, now=int(time.time()) + WEEK - 10) == (None, 'fresh')


def test_auto_import_lease_blocks_manual_request_from_other_process(download):
    from price_mixer.services.catalog_refresh import CatalogRefreshState
    fetch, _ = download
    token, _ = CatalogRefreshState(svc.db_connection).claim('test-sheet:All_Catalog')
    body, status = fetch()
    assert status == 409 and body['status'] == 'already_running'


def test_failed_worker_does_not_count_as_successful_refresh(download, monkeypatch):
    fetch, _ = download
    monkeypatch.setattr(svc.urllib.request, 'urlopen', lambda *_a, **_k: response(CORE))
    def fail(*args, **kwargs):
        svc.catalog_import_status.update(running=False, message='Ошибка импорта')
        return False
    monkeypatch.setattr(svc, 'catalog_import_worker', fail)
    fetch()
    with svc.db_connection() as conn:
        row = conn.execute('SELECT last_success, token FROM catalog_refresh_state').fetchone()
        assert row['last_success'] == 0 and row['token'] == ''


def test_google_query_selects_only_used_columns_and_explicit_header(download, monkeypatch):
    fetch, imported = download
    requests = []

    def open_url(request, **kwargs):
        requests.append(request.full_url)
        return response(CORE)

    monkeypatch.setattr(svc.urllib.request, "urlopen", open_url)
    assert fetch()["status"] == "started"
    assert len(requests) == 1
    query = parse_qs(urlparse(requests[0]).query)
    assert query["headers"] == ["1"]
    assert query["tq"] == ["select A,C,E,H"]
    assert query["sheet"] == ["All_Catalog"]
    assert imported[0][0][1][4] == "12345"
    assert imported[0][0][1][7] == "Kingston NV2"
    assert imported[0][1]["cleanup_file"] is False


def test_invalid_google_response_falls_back_before_import(download, monkeypatch):
    fetch, imported = download
    bodies = iter([b"<html>Sign in</html>", FULL])
    monkeypatch.setattr(svc.urllib.request, "urlopen", lambda *_a, **_k: response(next(bodies)))
    fetch()
    assert len(imported) == 1
    assert imported[0][0][1][4] == "12345"


def test_google_folded_header_is_rejected(download, monkeypatch):
    fetch, imported = download
    bodies = iter([b'"Category SSD SSD","Model NV2","onliner_id 12345","Specs Kingston"\n', FULL])
    monkeypatch.setattr(svc.urllib.request, "urlopen", lambda *_a, **_k: response(next(bodies)))
    fetch()
    assert len(imported) == 1
    assert len(imported[0][0][0]) == 8


def test_cached_projection_is_reused_only_without_force_refresh(download, monkeypatch):
    fetch, imported = download
    calls = []
    monkeypatch.setattr(svc.urllib.request, "urlopen", lambda *_a, **_k: calls.append(True) or response(CORE))
    fetch()
    fetch(force=False)
    assert len(calls) == 1
    assert len(imported) == 2
    fetch(force=True)
    assert len(calls) == 2


def test_failed_download_keeps_previous_cache_and_cleans_temp(download, monkeypatch, tmp_path):
    fetch, imported = download
    cached = tmp_path / "test-sheet_All_Catalog_core_v2.csv"
    cached.write_bytes(CORE)
    create_temp = svc.tempfile.NamedTemporaryFile

    def make_temp(**kwargs):
        return create_temp(dir=tmp_path, **kwargs)

    monkeypatch.setattr(svc.tempfile, "NamedTemporaryFile", make_temp)
    monkeypatch.setattr(svc.urllib.request, "urlopen", lambda *_a, **_k: response(b"bad response"))
    fetch()
    assert not imported
    assert cached.read_bytes() == CORE
    assert svc.import_status_payload()["running"] is False
    assert svc.import_status_payload()["message"].startswith("Ошибка")
    assert [p.name for p in tmp_path.iterdir() if not p.name.startswith("catalog.db")] == [cached.name]


def test_second_import_cannot_start_while_first_thread_is_queued(download):
    fetch, _ = download
    queued = []
    assert fetch(start=queued.append)["status"] == "started"
    body, code = fetch(start=queued.append)
    assert code == 409
    assert body["status"] == "already_running"
    assert len(queued) == 1


def test_thread_start_failure_releases_import(download):
    fetch, _ = download

    def fail(_target):
        raise RuntimeError("no thread")

    body, code = fetch(start=fail)
    assert code == 500
    assert body["status"] == "error"
    assert svc.import_status_payload()["running"] is False
