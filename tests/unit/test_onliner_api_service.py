"""Unit tests for Onliner public API gateway service."""

import pytest

from price_mixer.services import onliner_api


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code
        self.ok = 200 <= status_code < 400


class _Session:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, timeout=None, headers=None, proxies=None):
        self.calls.append({
            "url": url,
            "timeout": timeout,
            "headers": dict(headers or {}),
            "proxies": proxies,
        })
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _settings(**overrides):
    data = {
        "allow_direct": True,
        "proxy_pool": [],
        "retry_attempts": 3,
        "backoff_sec": 0,
        "proxy_cooldown_sec": 30,
        "max_parallel_workers": 8,
    }
    data.update(overrides)
    return data


def test_onliner_api_get_uses_direct_route_and_merges_headers(monkeypatch):
    session = _Session([_Response(200)])
    onliner_api.ONLINER_API_PROXY_STATE.clear()
    monkeypatch.setattr(onliner_api, "load_onliner_api_settings", lambda: _settings())
    monkeypatch.setattr(onliner_api, "_get_session", lambda: session)

    response = onliner_api.onliner_api_get("https://catalog.onliner.by/item", timeout=5, headers={"X-Test": "1"})

    assert response.status_code == 200
    assert session.calls == [{
        "url": "https://catalog.onliner.by/item",
        "timeout": 5,
        "headers": {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "X-Test": "1"},
        "proxies": None,
    }]
    assert onliner_api.ONLINER_API_PROXY_STATE["direct"]["last_status"] == 200


def test_onliner_api_get_retries_retryable_status_through_proxy(monkeypatch):
    proxy = {"key": "p1", "proxies": {"https": "http://proxy.local:8080"}}
    session = _Session([_Response(429), _Response(200)])
    onliner_api.ONLINER_API_PROXY_STATE.clear()
    monkeypatch.setattr(onliner_api, "load_onliner_api_settings", lambda: _settings(proxy_pool=[proxy], retry_attempts=2))
    monkeypatch.setattr(onliner_api, "_get_session", lambda: session)
    monkeypatch.setattr(onliner_api.time, "sleep", lambda _seconds: None)

    response = onliner_api.onliner_api_get("https://catalog.onliner.by/item")

    assert response.status_code == 200
    assert session.calls[0]["proxies"] is None
    assert session.calls[1]["proxies"] == {"https": "http://proxy.local:8080"}
    assert onliner_api.ONLINER_API_PROXY_STATE["direct"]["last_status"] == 429
    assert onliner_api.ONLINER_API_PROXY_STATE["p1"]["last_status"] == 200


def test_onliner_api_get_honors_disabled_direct_route(monkeypatch):
    proxy = {"key": "p1", "proxies": {"https": "http://proxy.local:8080"}}
    session = _Session([_Response(200)])
    onliner_api.ONLINER_API_PROXY_STATE.clear()
    monkeypatch.setattr(onliner_api, "load_onliner_api_settings", lambda: _settings(allow_direct=False, proxy_pool=[proxy]))
    monkeypatch.setattr(onliner_api, "_get_session", lambda: session)

    response = onliner_api.onliner_api_get("https://catalog.onliner.by/item")

    assert response.status_code == 200
    assert session.calls[0]["proxies"] == {"https": "http://proxy.local:8080"}
    assert "direct" not in onliner_api.ONLINER_API_PROXY_STATE


def test_onliner_api_get_raises_last_error_when_all_routes_fail(monkeypatch):
    session = _Session([TimeoutError("boom")])
    onliner_api.ONLINER_API_PROXY_STATE.clear()
    monkeypatch.setattr(onliner_api, "load_onliner_api_settings", lambda: _settings(retry_attempts=1))
    monkeypatch.setattr(onliner_api, "_get_session", lambda: session)

    with pytest.raises(TimeoutError):
        onliner_api.onliner_api_get("https://catalog.onliner.by/item")

    assert onliner_api.ONLINER_API_PROXY_STATE["direct"]["last_error"] == "TimeoutError"
