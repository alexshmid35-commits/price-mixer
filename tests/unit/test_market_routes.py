"""Unit tests for market refresh API blueprint."""

from flask import Flask

from price_mixer.api.market_routes import create_market_bp, format_market_refresh_status


def _make_app(get_session=lambda: "/tmp/session", start=None, status=None):
    app = Flask(__name__)
    app.register_blueprint(create_market_bp(
        get_active_session_dir=get_session,
        start_market_refresh=start or (lambda session_dir, categories: {"status": "started", "categories": categories}),
        get_market_refresh_status=status or (lambda: {}),
    ))
    return app


def test_format_market_refresh_status_normalizes_payload():
    payload = format_market_refresh_status({
        "running": True,
        "total": 4,
        "done": 1,
        "success": "1",
        "errors": None,
        "started_at": "10",
        "finished_at": "0",
        "recent_errors": ["x"],
        "phase": "running",
        "message": "work",
        "categories": {
            "CPU": {"done": "1", "total": "2", "percent": "50", "errors": "0", "recent_errors": ["cpu"]},
            "bad": "ignored",
        },
    })

    assert payload["running"] is True
    assert payload["overall_percent"] == 25
    assert payload["success"] == 1
    assert payload["errors"] == 0
    assert payload["categories"]["CPU"]["percent"] == 50
    assert "bad" not in payload["categories"]
    assert payload["phase"] == "running"
    assert payload["message"] == "work"


def test_market_refresh_start_requires_session():
    app = _make_app(get_session=lambda: None)

    with app.test_client() as client:
        resp = client.post("/api/market-refresh-start", json={"categories": ["CPU"]})

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "error", "message": "No session"}


def test_market_refresh_start_normalizes_categories():
    called = {}

    def _start(session_dir, categories):
        called["session_dir"] = session_dir
        called["categories"] = categories
        return {"status": "started"}

    app = _make_app(start=_start)

    with app.test_client() as client:
        resp = client.post("/api/market-refresh-start", json={"categories": "not-list"})

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "started"
    assert called == {"session_dir": "/tmp/session", "categories": []}


def test_market_refresh_status_endpoint_formats_snapshot():
    app = _make_app(status=lambda: {"running": False, "total": 10, "done": 3})

    with app.test_client() as client:
        resp = client.get("/api/market-refresh-status")

    assert resp.status_code == 200
    assert resp.get_json()["overall_percent"] == 30
