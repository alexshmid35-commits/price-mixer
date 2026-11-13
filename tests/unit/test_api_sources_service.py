"""Unit tests for API source runtime and fetch worker helpers."""

import zipfile
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
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("xl/workbook.xml", "<workbook/>")

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
    assert get_source_runtime(source_key, "client1")["total_bytes"] == target.stat().st_size


def test_curl_download_to_path_rejects_iven_bad_password_response(tmp_path, monkeypatch):
    api_sources.source_fetch_statuses.clear()
    target = tmp_path / "iven_zakaz.xlsx"

    class FakeProc:
        returncode = 0

        def __init__(self, cmd, stdout=None, stderr=None):
            target.write_bytes(b"Bad password")

        def poll(self):
            return 0

        def communicate(self, timeout=None):
            return b"", b""

        def kill(self):
            pass

        def terminate(self):
            pass

    monkeypatch.setattr(api_sources, "resolve_curl_cmd", lambda: "curl")
    monkeypatch.setattr(api_sources.subprocess, "Popen", FakeProc)

    with pytest.raises(PermissionError, match="отклонил логин или пароль"):
        api_sources.curl_download_to_path(
            "https://example.test/price.xlsx",
            target,
            False,
            "iven_zakaz",
            "client1",
        )

    assert get_source_runtime("iven_zakaz", "client1")["progress"] != 100


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


def test_curl_download_retries_stop_immediately_for_rejected_credentials(tmp_path, monkeypatch):
    target = tmp_path / "iven_zakaz.xlsx"
    calls = []

    def _curl_download(*args, **kwargs):
        calls.append("curl")
        target.write_bytes(b"Bad password")
        raise PermissionError("IVEN отклонил логин или пароль")

    monkeypatch.setattr(api_sources, "curl_download_to_path", _curl_download)
    monkeypatch.setattr(
        api_sources,
        "ssh_download_to_path",
        lambda *args, **kwargs: pytest.fail("SSH must not run for rejected credentials"),
    )
    monkeypatch.setattr(
        api_sources.time,
        "sleep",
        lambda seconds: pytest.fail("Credential errors must not be retried"),
    )
    monkeypatch.setenv("PRICE_MIXER_IVEN_ZAKAZ_SSH_HOST", "root@example.test")

    with pytest.raises(PermissionError, match="отклонил логин или пароль"):
        api_sources.curl_download_to_path_with_retries(
            "https://example.test/iven-zakaz.xlsx",
            target,
            False,
            "iven_zakaz",
            "client1",
            attempts=3,
        )

    assert calls == ["curl"]
    assert not target.exists()


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


@pytest.mark.parametrize("text", [
    "Прайс уже формируется. Повторите запрос через 5 секунд.",
    "Прайс-лист генерируется. Повторите запрос через 5 секунд.",
])
def test_iven_generation_response_is_not_a_corrupt_workbook(tmp_path, text):
    path = tmp_path / 'order.xlsx'
    path.write_text(text, encoding='utf-8')
    with pytest.raises(api_sources.IvenPricePendingError):
        api_sources._validate_iven_download(path)


def test_pending_order_price_is_polled_on_ssh_without_restarting_direct_route(tmp_path, monkeypatch):
    path = tmp_path / 'order.xlsx'
    calls, sleeps = [], []
    monkeypatch.setenv('PRICE_MIXER_IVEN_ZAKAZ_SSH_HOST', 'root@example.test')
    monkeypatch.setattr(api_sources.time, 'sleep', sleeps.append)
    def local(*args, **kwargs):
        calls.append('direct')
        raise RuntimeError('curl: (56) Connection reset by peer')
    def remote(*args, **kwargs):
        calls.append('ssh')
        if calls.count('ssh') <= 2:
            path.write_text('Прайс уже формируется. Повторите запрос через 5 секунд.')
        else:
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('xl/workbook.xml', '<workbook/>')
        api_sources._validate_iven_download(path)
    monkeypatch.setattr(api_sources, 'curl_download_to_path', local)
    monkeypatch.setattr(api_sources, 'ssh_download_to_path', remote)
    api_sources.curl_download_to_path_with_retries('https://example.test', path, False, 'iven_zakaz', 'test')
    assert calls == ['direct', 'ssh', 'ssh', 'ssh']
    assert sleeps == [5, 5]
    assert zipfile.is_zipfile(path)


def test_generation_wait_is_bounded_and_never_marks_pending_ready(tmp_path, monkeypatch):
    path = tmp_path / 'order.xlsx'
    calls = []
    monkeypatch.setattr(api_sources.time, 'sleep', lambda _: None)
    def pending():
        calls.append(True)
        path.write_text('Прайс уже формируется.')
        api_sources._validate_iven_download(path)
    with pytest.raises(TimeoutError):
        api_sources._wait_for_iven_price(pending, path, 'iven_zakaz', 'bounded', max_waits=2)
    assert len(calls) == 3
    assert not path.exists()
    assert not get_source_runtime('iven_zakaz', 'bounded')['ready']


def test_generation_deadline_stops_polling_even_with_fewer_attempts(tmp_path, monkeypatch):
    path = tmp_path / 'order.xlsx'
    clock = iter([0, 121])
    monkeypatch.setattr(api_sources.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(api_sources.time, 'sleep', lambda _: pytest.fail('deadline expired'))
    def pending():
        path.write_text('Прайс уже формируется.')
        api_sources._validate_iven_download(path)
    with pytest.raises(TimeoutError):
        api_sources._wait_for_iven_price(pending, path, 'iven_zakaz', 'deadline')
    assert not path.exists()


def test_iven_rate_limit_uses_retry_after_not_generic_file_error(tmp_path):
    path = tmp_path / 'order.xlsx'
    path.write_text('Слишком частое скачивание прайса. Повторите через 9 мин.')
    with pytest.raises(api_sources.IvenRateLimitError) as exc:
        api_sources._validate_iven_download(path, 'HTTP/1.1 429 Too Many Requests\r\nRetry-After: 537\r\n')
    assert exc.value.retry_after == 537
    assert '9 мин' in str(exc.value)
    assert 'поврежденный' not in str(exc.value)


def test_iven_rate_limit_body_is_recognized_without_headers(tmp_path):
    path = tmp_path / 'order.xlsx'
    path.write_text('Слишком частое скачивание прайса. Повторите через 9 мин.')
    with pytest.raises(api_sources.IvenRateLimitError) as exc:
        api_sources._validate_iven_download(path)
    assert exc.value.retry_after == 540


def test_rate_limit_does_not_switch_ip_or_retry_until_deadline(tmp_path, monkeypatch):
    path = tmp_path / 'order.xlsx'
    monkeypatch.setattr(api_sources, 'SOURCE_RUNTIME_DIR', tmp_path / 'runtime')
    monkeypatch.setenv('PRICE_MIXER_IVEN_ZAKAZ_SSH_HOST', 'root@example.test')
    clock = [1000]
    monkeypatch.setattr(api_sources.time, 'time', lambda: clock[0])
    monkeypatch.setattr(api_sources.time, 'sleep', lambda _: pytest.fail('must defer, not block worker'))
    calls = []
    def local(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            path.write_text('limited')
            raise api_sources.IvenRateLimitError(537)
        path.write_bytes(b'price')
    monkeypatch.setattr(api_sources, 'curl_download_to_path', local)
    monkeypatch.setattr(api_sources, 'ssh_download_to_path', lambda *a, **k: pytest.fail('must not evade rate limit'))
    url = 'https://example.test/?password=secret'
    for _ in range(2):
        with pytest.raises(api_sources.IvenRateLimitError):
            api_sources.curl_download_to_path_with_retries(url, path, False, 'iven_zakaz', 'rate')
    assert len(calls) == 1 and not path.exists()
    cache = list((tmp_path / 'runtime' / 'iven_cooldowns').glob('*.json'))[0]
    assert 'secret' not in cache.name + cache.read_text()
    clock[0] = 1538
    api_sources.curl_download_to_path_with_retries(url, path, False, 'iven_zakaz', 'rate')
    assert len(calls) == 2


def test_transport_errors_do_not_expose_redirect_header_credentials():
    stderr = b'HTTP/1.1 302 Found\r\nLocation: https://example.test/?password=secret\r\ncurl: (56) Recv failure\n'
    assert api_sources._transport_error(stderr, 'error') == 'curl: (56) Recv failure'


def test_bad_password_on_ssh_is_not_wrapped_or_retried(tmp_path, monkeypatch):
    path = tmp_path / 'order.xlsx'
    monkeypatch.setenv('PRICE_MIXER_IVEN_ZAKAZ_SSH_HOST', 'root@example.test')
    def local(*args, **kwargs):
        raise RuntimeError('curl: (56) Connection reset by peer')
    def remote(*args, **kwargs):
        path.write_bytes(b'Bad password')
        api_sources._validate_iven_download(path)
    monkeypatch.setattr(api_sources, 'curl_download_to_path', local)
    monkeypatch.setattr(api_sources, 'ssh_download_to_path', remote)
    monkeypatch.setattr(api_sources.time, 'sleep', lambda _: pytest.fail('must not retry credentials'))
    with pytest.raises(PermissionError):
        api_sources.curl_download_to_path_with_retries('https://example.test', path, False, 'iven_zakaz', 'test')
    assert not path.exists()


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
