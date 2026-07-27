"""Unit tests for API source runtime and fetch worker helpers."""

from pathlib import Path

import pytest

from price_mixer.services import api_sources
from price_mixer.services.api_sources import (
    build_ntech_dataframe,
    fetch_api_source_worker,
    get_api_source_status_key,
    get_client_source_state,
    get_source_runtime,
    iter_api_sources_for_ui,
    ntech_reserve_url_from_price_url,
    process_source_batch_payload,
    process_source_payload,
    serialize_source_runtime,
    source_fetch_start_payload,
    source_fetch_status_payload,
    update_source_runtime,
)


def test_get_api_source_status_key_reuses_session_value():
    session = {}

    first = get_api_source_status_key(session)
    second = get_api_source_status_key(session)

    assert first
    assert first == second
    assert session["api_fetch_key"] == first


def test_runtime_update_and_serialization():
    api_sources.source_fetch_statuses.clear()

    update_source_runtime("iven", "client1", progress="42", started_at=10.9)
    state = get_source_runtime("iven", "client1")

    assert state["progress"] == "42"
    assert get_client_source_state("client1")["iven"] is state
    assert serialize_source_runtime(state)["progress"] == 42


def test_iter_api_sources_for_ui_marks_configured_sources():
    settings = {
        "api_sources": {
            "iven": {"label": "IVEN", "supplier": "IVEN", "enabled": True, "file_url": "https://example/file.xlsx"},
            "ntech": {
                "label": "N-Tech",
                "supplier": "N-Tech",
                "enabled": True,
                "mode": "ntech_json",
                "auth_url": "a",
                "price_url": "p",
                "username": "u",
                "password": "pw",
            },
            "empty": {"mode": "direct_file"},
        }
    }

    items = {item["key"]: item for item in iter_api_sources_for_ui(settings)}

    assert items["iven"]["configured"] is True
    assert items["ntech"]["configured"] is True
    assert items["empty"]["configured"] is False


def test_source_fetch_start_initializes_runtime_and_starts_worker():
    api_sources.source_fetch_statuses.clear()
    started = []

    body, status = source_fetch_start_payload(
        {"source": "IVEN"},
        client_key="client1",
        settings={"api_sources": {"iven": {"label": "IVEN"}}},
        start_worker=lambda source_key, client_key: started.append((source_key, client_key)),
        now=lambda: 100.5,
    )

    assert status == 200
    assert body["status"] == "ok"
    assert body["state"]["running"] is True
    assert body["state"]["status"] == "starting"
    assert started == [("iven", "client1")]


def test_source_fetch_status_builds_items_with_runtime_and_history():
    api_sources.source_fetch_statuses.clear()
    update_source_runtime("iven", "client1", progress=55, label="IVEN runtime")

    body, status = source_fetch_status_payload(
        "",
        client_key="client1",
        settings={"api_sources": {"iven": {"label": "IVEN", "supplier": "IVEN", "enabled": True, "file_url": "u"}}},
        history=[{"status": "ok"}],
    )

    assert status == 200
    assert body["items"][0]["source_key"] == "iven"
    assert body["items"][0]["progress"] == 55
    assert body["items"][0]["configured"] is True
    assert body["history"] == [{"status": "ok"}]


def test_ntech_reserve_url_from_price_url():
    assert ntech_reserve_url_from_price_url("https://api.example/orders/v1/price") == "https://api.example/orders/v1/list"
    assert ntech_reserve_url_from_price_url("https://api.example/orders/v1") == "https://api.example/orders/v1/list"


def test_build_ntech_dataframe_includes_category_rows():
    df = build_ntech_dataframe({
        "products": [
            {"category": "SSD", "id": "1", "name": "Drive", "price": "10", "price_with_vat": "12"},
            {"category": "SSD", "id": "2", "name": "Drive 2", "price": "20"},
        ]
    })

    assert list(df["Наименование"]) == ["", "Drive", "Drive 2"]
    assert df.iloc[0][""] == "SSD"


def test_fetch_api_source_worker_direct_file_success(tmp_path, monkeypatch):
    api_sources.source_fetch_statuses.clear()
    history = []

    def _stream_download(url, target_path, verify_ssl, source_key, client_key, headers=None):
        Path(target_path).write_bytes(b"price")
        update_source_runtime(source_key, client_key, downloaded=5, progress=100)

    monkeypatch.setattr(api_sources, "stream_download_to_path", _stream_download)

    fetch_api_source_worker(
        "bn",
        "client1",
        upload_dir=tmp_path,
        load_settings=lambda: {
            "api_sources": {
                "bn": {
                    "label": "BN",
                    "supplier": "BN",
                    "mode": "direct_file",
                    "file_url": "https://example/file.xlsx",
                    "verify_ssl": True,
                }
            }
        },
        append_history=history.append,
    )

    state = get_source_runtime("bn", "client1")
    assert state["status"] == "ready"
    assert state["ready"] is True
    assert Path(state["file_path"]).read_bytes() == b"price"
    assert history[-1]["status"] == "ok"


def test_fetch_api_source_worker_retries_direct_json_retry_after(tmp_path, monkeypatch):
    api_sources.source_fetch_statuses.clear()
    history = []
    calls = []
    sleeps = []

    def _stream_download(url, target_path, verify_ssl, source_key, client_key, headers=None):
        calls.append(url)
        if len(calls) == 1:
            Path(target_path).write_text('{"status":1,"detail":"Прайс-лист генерируется","retry_after":"5"}', encoding="utf-8")
        else:
            Path(target_path).write_bytes(b"PK\x03\x04price")
        update_source_runtime(source_key, client_key, downloaded=Path(target_path).stat().st_size, progress=80)

    monkeypatch.setattr(api_sources, "stream_download_to_path", _stream_download)
    monkeypatch.setattr(api_sources.time, "sleep", lambda seconds: sleeps.append(seconds))

    fetch_api_source_worker(
        "tradex",
        "client1",
        upload_dir=tmp_path,
        load_settings=lambda: {
            "api_sources": {
                "tradex": {
                    "label": "Tradex",
                    "supplier": "Tradex",
                    "mode": "direct_file",
                    "file_url": "https://example/tradex.xlsx",
                    "verify_ssl": True,
                }
            }
        },
        append_history=history.append,
    )

    state = get_source_runtime("tradex", "client1")
    assert calls == ["https://example/tradex.xlsx", "https://example/tradex.xlsx"]
    assert sleeps == [5]
    assert state["status"] == "ready"
    assert state["ready"] is True
    assert Path(state["file_path"]).read_bytes().startswith(b"PK\x03\x04")
    assert history[-1]["status"] == "ok"


def test_fetch_api_source_worker_reports_direct_json_instead_of_ready_file(tmp_path, monkeypatch):
    api_sources.source_fetch_statuses.clear()
    history = []

    def _stream_download(url, target_path, verify_ssl, source_key, client_key, headers=None):
        Path(target_path).write_text('{"status":1,"detail":"Прайс-лист генерируется","retry_after":"0"}', encoding="utf-8")
        update_source_runtime(source_key, client_key, downloaded=Path(target_path).stat().st_size, progress=80)

    monkeypatch.setattr(api_sources, "stream_download_to_path", _stream_download)

    fetch_api_source_worker(
        "tradex",
        "client1",
        upload_dir=tmp_path,
        load_settings=lambda: {
            "api_sources": {
                "tradex": {
                    "label": "Tradex",
                    "supplier": "Tradex",
                    "mode": "direct_file",
                    "file_url": "https://example/tradex.xlsx",
                }
            }
        },
        append_history=history.append,
    )

    state = get_source_runtime("tradex", "client1")
    assert state["status"] == "error"
    assert state["ready"] is False
    assert "Прайс-лист генерируется" in state["message"]
    assert history[-1]["status"] == "error"


@pytest.mark.parametrize("source_key", ["iven", "iven_zakaz"])
def test_curl_download_to_path_iven_sources_use_direct_get_without_head_or_range(tmp_path, monkeypatch, source_key):
    api_sources.source_fetch_statuses.clear()
    target = tmp_path / f"{source_key}.xlsx"
    captured = []

    def _head(*args, **kwargs):
        raise AssertionError("IVEN download should not run a separate HEAD request")

    class FakeProc:
        returncode = 0

        def __init__(self, cmd, stdout=None, stderr=None):
            captured.append(cmd)
            target.write_bytes(b"price")

        def poll(self):
            return 0

        def communicate(self, timeout=None):
            return b"", b""

        def kill(self):
            pass

        def terminate(self):
            pass

    monkeypatch.setattr(api_sources, "resolve_curl_cmd", lambda: "curl")
    monkeypatch.setattr(api_sources, "head_content_length_via_curl", _head)
    monkeypatch.setattr(api_sources.subprocess, "Popen", FakeProc)

    api_sources.curl_download_to_path(
        "https://example.test/price.xlsx",
        target,
        False,
        source_key,
        "client1",
        headers={"X-Test": "1"},
    )

    cmd = captured[0]
    assert "-I" not in cmd
    assert "-r" not in cmd
    assert "--http1.1" in cmd
    assert "-k" in cmd
    assert ["-H", "X-Test: 1"] == cmd[cmd.index("-H"):cmd.index("-H") + 2]
    assert get_source_runtime(source_key, "client1")["total_bytes"] == 5


def test_curl_download_to_path_with_retries_recovers_after_iven_reset(tmp_path, monkeypatch):
    api_sources.source_fetch_statuses.clear()
    target = tmp_path / "iven.xlsx"
    calls = []
    sleeps = []

    def _curl_download(url, target_path, verify_ssl, source_key, client_key, headers=None):
        calls.append((url, source_key))
        if len(calls) == 1:
            Path(target_path).write_bytes(b"partial")
            raise RuntimeError("curl: (56) Recv failure: Connection reset by peer")
        Path(target_path).write_bytes(b"price")
        update_source_runtime(source_key, client_key, downloaded=5, total_bytes=5, progress=100)

    monkeypatch.setattr(api_sources, "curl_download_to_path", _curl_download)
    monkeypatch.setattr(api_sources.time, "sleep", lambda seconds: sleeps.append(seconds))

    api_sources.curl_download_to_path_with_retries(
        "https://example.test/iven.xlsx",
        target,
        False,
        "iven",
        "client1",
        attempts=2,
        retry_delay_sec=3,
    )

    assert calls == [
        ("https://example.test/iven.xlsx", "iven"),
        ("https://example.test/iven.xlsx", "iven"),
    ]
    assert sleeps == [3]
    assert target.read_bytes() == b"price"
    assert get_source_runtime("iven", "client1")["status"] == "downloading"
    assert get_source_runtime("iven", "client1")["progress"] == 100


def test_curl_download_to_path_with_retries_uses_ssh_fallback_for_iven_zakaz(tmp_path, monkeypatch):
    api_sources.source_fetch_statuses.clear()
    target = tmp_path / "iven_zakaz.xlsx"
    local_calls = []
    fallback_calls = []

    def _curl_download(url, target_path, verify_ssl, source_key, client_key, headers=None):
        local_calls.append((url, source_key))
        raise RuntimeError("curl: (56) Recv failure: Connection reset by peer")

    def _ssh_download(url, target_path, verify_ssl, source_key, client_key, headers=None, *, host):
        fallback_calls.append((url, source_key, host))
        Path(target_path).write_bytes(b"price")
        update_source_runtime(source_key, client_key, downloaded=5, total_bytes=5, progress=100)

    monkeypatch.setattr(api_sources, "curl_download_to_path", _curl_download)
    monkeypatch.setattr(api_sources, "ssh_download_to_path", _ssh_download)
    monkeypatch.setenv("PRICE_MIXER_IVEN_ZAKAZ_SSH_HOST", "root@example.test")

    api_sources.curl_download_to_path_with_retries(
        "https://example.test/iven-zakaz.xlsx",
        target,
        False,
        "iven_zakaz",
        "client1",
        attempts=3,
    )

    assert local_calls == [("https://example.test/iven-zakaz.xlsx", "iven_zakaz")]
    assert fallback_calls == [
        ("https://example.test/iven-zakaz.xlsx", "iven_zakaz", "root@example.test")
    ]
    assert target.read_bytes() == b"price"


def test_iven_ssh_fallback_host_is_scoped_and_validated(monkeypatch):
    monkeypatch.setenv("PRICE_MIXER_IVEN_ZAKAZ_SSH_HOST", "root@example.test")

    assert api_sources.iven_ssh_fallback_host("iven_zakaz") == "root@example.test"
    assert api_sources.iven_ssh_fallback_host("iven") == ""

    monkeypatch.setenv("PRICE_MIXER_IVEN_ZAKAZ_SSH_HOST", "root@example.test;bad")
    with pytest.raises(ValueError, match="Некорректный SSH-хост"):
        api_sources.iven_ssh_fallback_host("iven_zakaz")


def test_fetch_api_source_worker_iven_uses_serialized_retry_downloader(tmp_path, monkeypatch):
    api_sources.source_fetch_statuses.clear()
    history = []
    calls = []

    def _curl_download_with_retries(url, target_path, verify_ssl, source_key, client_key, headers=None):
        calls.append((url, source_key))
        Path(target_path).write_bytes(b"price")
        update_source_runtime(source_key, client_key, downloaded=5, total_bytes=5, progress=100)

    monkeypatch.setattr(api_sources, "curl_download_to_path_with_retries", _curl_download_with_retries)

    fetch_api_source_worker(
        "iven_zakaz",
        "client1",
        upload_dir=tmp_path,
        load_settings=lambda: {
            "api_sources": {
                "iven_zakaz": {
                    "label": "IVEN_ZAKAZ",
                    "supplier": "IVEN_zakaz",
                    "mode": "direct_file",
                    "file_url": "https://iven.pro:800/?price=4",
                    "verify_ssl": False,
                }
            }
        },
        append_history=history.append,
    )

    state = get_source_runtime("iven_zakaz", "client1")
    assert calls == [("https://iven.pro:800/?price=4", "iven_zakaz")]
    assert state["status"] == "ready"
    assert state["ready"] is True
    assert Path(state["file_path"]).read_bytes() == b"price"
    assert history[-1]["status"] == "ok"


def test_fetch_api_source_worker_records_error(tmp_path):
    api_sources.source_fetch_statuses.clear()
    history = []

    fetch_api_source_worker(
        "empty",
        "client1",
        upload_dir=tmp_path,
        load_settings=lambda: {"api_sources": {"empty": {"mode": "direct_file", "file_url": ""}}},
        append_history=history.append,
    )

    state = get_source_runtime("empty", "client1")
    assert state["status"] == "error"
    assert history[-1]["status"] == "error"


def test_process_source_payload_processes_ready_file(tmp_path):
    api_sources.source_fetch_statuses.clear()
    price_path = tmp_path / "iven.xlsx"
    price_path.write_bytes(b"price")
    update_source_runtime(
        "iven",
        "client1",
        ready=True,
        file_path=str(price_path),
        file_name="iven.xlsx",
        supplier="IVEN",
        label="IVEN",
    )
    history = []
    finalized = []

    def _process(files):
        assert files == [{"filepath": price_path, "display_name": "iven.xlsx", "supplier_name": "IVEN"}]
        return {
            "session_id": "sid1",
            "session_dir": "/tmp/sid1",
            "output_path": "/tmp/sid1/consolidated_price.xlsx",
            "stats": {"consolidated": 10, "without_id": 2},
        }

    body, status = process_source_payload(
        {"source": "IVEN"},
        client_key="client1",
        process_supplier_files=_process,
        finalize_processed_session=lambda sid, session_dir, output_path: finalized.append((sid, session_dir, output_path)),
        append_history=history.append,
        redirect_for_session=lambda sid: f"/result/{sid}",
        now=lambda: 200,
    )

    assert status == 200
    assert body == {"status": "ok", "redirect_url": "/result/sid1"}
    assert finalized == [("sid1", "/tmp/sid1", "/tmp/sid1/consolidated_price.xlsx")]
    assert history[-1]["status"] == "ok"
    assert history[-1]["items_count"] == 10
    assert history[-1]["without_id_count"] == 2


def test_process_source_payload_rejects_missing_file_path():
    api_sources.source_fetch_statuses.clear()

    body, status = process_source_payload(
        {"source": "iven"},
        client_key="client1",
        process_supplier_files=lambda files: {},
        finalize_processed_session=lambda sid, session_dir, output_path: None,
        append_history=lambda record: None,
        redirect_for_session=lambda sid: f"/result/{sid}",
    )

    assert status == 400
    assert body["message"] == "Сначала выгрузи прайс"


def test_process_source_batch_payload_dedupes_and_records_each_source(tmp_path):
    api_sources.source_fetch_statuses.clear()
    iven_path = tmp_path / "iven.xlsx"
    ntech_path = tmp_path / "ntech.xlsx"
    iven_path.write_bytes(b"iven")
    ntech_path.write_bytes(b"ntech")
    update_source_runtime("iven", "client1", ready=True, file_path=str(iven_path), file_name="iven.xlsx", supplier="IVEN", label="IVEN")
    update_source_runtime("ntech", "client1", ready=True, file_path=str(ntech_path), file_name="ntech.xlsx", supplier="N-Tech", label="N-Tech")
    history = []

    def _process(files):
        assert [entry["supplier_name"] for entry in files] == ["IVEN", "N-Tech"]
        return {
            "session_id": "sid2",
            "session_dir": "/tmp/sid2",
            "output_path": "/tmp/sid2/consolidated_price.xlsx",
            "stats": {"consolidated": 22, "without_id": 3},
        }

    body, status = process_source_batch_payload(
        {"sources": ["iven", "IVEN", "ntech"]},
        client_key="client1",
        client_state=get_client_source_state("client1"),
        process_supplier_files=_process,
        finalize_processed_session=lambda sid, session_dir, output_path: None,
        append_history=history.append,
        redirect_for_session=lambda sid: f"/result/{sid}",
        now=lambda: 300,
    )

    assert status == 200
    assert body["processed_sources"] == ["iven", "ntech"]
    assert body["redirect_url"] == "/result/sid2"
    assert [record["source_key"] for record in history] == ["iven", "ntech"]
    assert {record["items_count"] for record in history} == {22}
