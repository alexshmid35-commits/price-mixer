"""Unit tests for Onliner URL resolve API blueprint."""

from flask import Flask, jsonify

from price_mixer.api.resolve_routes import create_resolve_bp


def _make_app(*, start=None, status=None):
    app = Flask(__name__)
    app.register_blueprint(create_resolve_bp(
        start=start or (lambda: {"status": "started", "total": 2}),
        status=status or (lambda: {"running": False, "resolved": 2}),
    ))
    return app


def test_resolve_start_returns_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/resolve-start")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "started", "total": 2}


def test_resolve_start_propagates_status():
    app = _make_app(start=lambda: ({"status": "error"}, 400))

    with app.test_client() as client:
        resp = client.post("/api/resolve-start")

    assert resp.status_code == 400
    assert resp.get_json() == {"status": "error"}


def test_resolve_status_returns_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/resolve-status")

    assert resp.status_code == 200
    assert resp.get_json() == {"running": False, "resolved": 2}


def test_resolve_accepts_flask_response():
    app = _make_app(status=lambda: jsonify({"running": True}))

    with app.test_client() as client:
        resp = client.get("/api/resolve-status")

    assert resp.status_code == 200
    assert resp.get_json() == {"running": True}


def test_resolve_start_rejects_get():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/resolve-start")

    assert resp.status_code == 405
