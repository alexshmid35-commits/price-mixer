"""Unit tests for API source fetch/process blueprint."""

from flask import Flask, jsonify

from price_mixer.api.source_routes import create_source_bp


def _make_app(*, handlers=None):
    app = Flask(__name__)
    app.register_blueprint(create_source_bp(
        handlers=handlers or {
            "/api/source-fetch-start": (lambda: {"status": "ok", "action": "fetch"}, ("POST",)),
            "/api/source-fetch-status": (lambda: {"status": "ok", "items": []}, ("GET",)),
            "/api/source-process": (lambda: ({"status": "error"}, 400), ("POST",)),
        },
    ))
    return app


def test_source_fetch_start_returns_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/source-fetch-start", json={"source": "iven"})

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "action": "fetch"}


def test_source_fetch_status_returns_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/source-fetch-status?source=iven")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "items": []}


def test_source_process_propagates_status():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/source-process", json={"source": "iven"})

    assert resp.status_code == 400
    assert resp.get_json() == {"status": "error"}


def test_source_accepts_flask_response():
    def _handler():
        return jsonify({"status": "ok"})

    app = _make_app(handlers={"/api/source-process-batch": (_handler, ("POST",))})

    with app.test_client() as client:
        resp = client.post("/api/source-process-batch", json={"sources": ["iven"]})

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_source_fetch_start_rejects_get():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/source-fetch-start")

    assert resp.status_code == 405
