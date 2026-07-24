"""Unit tests for autofill API blueprint."""

from flask import Flask, jsonify

from price_mixer.api.autofill_routes import create_autofill_bp


def _make_app(*, handlers=None):
    app = Flask(__name__)
    app.register_blueprint(create_autofill_bp(
        handlers=handlers or {
            "/api/autofill-tgpc-pc-ids": (lambda: {"status": "started"}, ("POST",)),
            "/api/autofill-tgpc-pc-status": (lambda: {"running": False}, ("GET",)),
            "/api/autofill-ntech-pc-ids": (lambda: {"status": "started"}, ("POST",)),
            "/api/autofill-ntech-pc-status": (lambda: {"running": False}, ("GET",)),
            "/api/autofill-iven-pc-ids": (lambda: {"status": "started"}, ("POST",)),
            "/api/autofill-iven-pc-status": (lambda: {"running": False}, ("GET",)),
            "/api/iven-reject-match": (lambda: ({"status": "error"}, 400), ("POST",)),
        },
    ))
    return app


def test_autofill_post_handler_returns_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/autofill-tgpc-pc-ids", json={"limit": 1})

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "started"}


def test_autofill_get_handler_returns_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/autofill-tgpc-pc-status")

    assert resp.status_code == 200
    assert resp.get_json() == {"running": False}


def test_autofill_iven_pc_routes_are_registered():
    app = _make_app()

    with app.test_client() as client:
        start_resp = client.post("/api/autofill-iven-pc-ids", json={})
        status_resp = client.get("/api/autofill-iven-pc-status")

    assert start_resp.status_code == 200
    assert start_resp.get_json() == {"status": "started"}
    assert status_resp.status_code == 200
    assert status_resp.get_json() == {"running": False}


def test_autofill_ntech_pc_routes_are_registered():
    app = _make_app()

    with app.test_client() as client:
        start_resp = client.post("/api/autofill-ntech-pc-ids", json={})
        status_resp = client.get("/api/autofill-ntech-pc-status")

    assert start_resp.status_code == 200
    assert start_resp.get_json() == {"status": "started"}
    assert status_resp.status_code == 200
    assert status_resp.get_json() == {"running": False}


def test_autofill_handler_propagates_status():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/iven-reject-match", json={})

    assert resp.status_code == 400
    assert resp.get_json() == {"status": "error"}


def test_autofill_accepts_flask_response_with_headers():
    def _handler():
        resp = jsonify({"running": True})
        resp.headers["Cache-Control"] = "no-store"
        return resp

    app = _make_app(handlers={"/api/autofill-iven-status": (_handler, ("GET",))})

    with app.test_client() as client:
        resp = client.get("/api/autofill-iven-status")

    assert resp.status_code == 200
    assert resp.get_json() == {"running": True}
    assert resp.headers["Cache-Control"] == "no-store"


def test_autofill_rejects_wrong_method():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/autofill-tgpc-pc-ids")

    assert resp.status_code == 405
