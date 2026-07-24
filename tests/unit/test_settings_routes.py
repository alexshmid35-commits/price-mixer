"""Unit tests for settings API blueprint."""

from flask import Flask

from price_mixer.api import settings_routes


def _make_app(save_app_settings=None):
    app = Flask(__name__)
    app.register_blueprint(settings_routes.create_settings_bp(
        get_active_session_dir=lambda: None,
        get_last_active_session_dir=lambda: None,
        start_market_refresh=lambda session_dir, categories: {"status": "error", "message": "no session"},
        save_app_settings=save_app_settings or (lambda payload: payload),
    ))
    return app


def test_app_settings_get_redacts_secrets(monkeypatch):
    monkeypatch.setattr(settings_routes, "load_app_settings", lambda: {
        "onliner_b2b": {"client_secret": "secret"},
        "api_sources": {
            "iven": {"file_url": "https://example.test/iven.xlsx"},
            "tradex": {"file_url": "https://example.test/tradex.xlsx"},
            "ntech": {"password": "pass"},
        },
    })
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/app-settings")

    assert resp.status_code == 200
    data = resp.get_json()["settings"]
    assert data["onliner_b2b"]["client_secret"] == "••••••••"
    assert data["api_sources"]["iven"]["file_url"] == "••••••••"
    assert data["api_sources"]["tradex"]["file_url"] == "••••••••"
    assert data["api_sources"]["ntech"]["password"] == "••••••••"


def test_app_settings_post_preserves_redacted_secrets(monkeypatch):
    saved_payload = {}
    monkeypatch.setattr(settings_routes, "load_app_settings", lambda: {
        "onliner_b2b": {"client_secret": "secret"},
        "api_sources": {
            "iven": {"file_url": "https://example.test/iven.xlsx"},
            "ntech": {"password": "pass"},
        },
    })

    def _save(payload):
        saved_payload.update(payload)
        return payload

    app = _make_app(save_app_settings=_save)

    with app.test_client() as client:
        resp = client.post(
            "/api/app-settings",
            json={
                "onliner_b2b": {"client_secret": "••••••••"},
                "api_sources": {
                    "iven": {"file_url": "••••••••"},
                    "ntech": {"password": "••••••••"},
                },
            },
        )

    assert resp.status_code == 200
    assert saved_payload["onliner_b2b"]["client_secret"] == "secret"
    assert saved_payload["api_sources"]["iven"]["file_url"] == "https://example.test/iven.xlsx"
    assert saved_payload["api_sources"]["ntech"]["password"] == "pass"


def test_auto_refresh_settings_get(monkeypatch):
    monkeypatch.setattr(settings_routes, "load_auto_refresh_settings", lambda: {
        "enabled": True,
        "interval_hours": 99,
        "last_run_ts": 100,
        "last_started_ts": 90,
        "last_status": "ok",
        "last_count": 12,
        "last_message": "done",
    })
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/auto-refresh-settings")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["enabled"] is True
    assert data["interval_hours"] == 12
    assert data["last_count"] == 12
