"""Unit tests for Onliner diagnostics/offers API blueprint."""

from flask import Flask, jsonify

from price_mixer.api.onliner_routes import create_onliner_bp


def _make_app(*, b2b_test=None, b2b_probe=None, get_offers=None):
    app = Flask(__name__)
    app.register_blueprint(create_onliner_bp(
        b2b_test=b2b_test or (lambda: {"status": "ok", "kind": "test"}),
        b2b_probe=b2b_probe or (lambda: ({"status": "error"}, 400)),
        get_offers=get_offers or (lambda onliner_id: {"status": "ok", "id": onliner_id}),
    ))
    return app


def test_onliner_b2b_test_returns_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/onliner-b2b-test")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "kind": "test"}


def test_onliner_b2b_probe_propagates_status():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/onliner-b2b-probe")

    assert resp.status_code == 400
    assert resp.get_json() == {"status": "error"}


def test_onliner_offers_passes_path_parameter():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/onliner-offers/12345")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "id": "12345"}


def test_onliner_routes_accept_flask_response():
    def _handler(onliner_id):
        return jsonify({"id": onliner_id})

    app = _make_app(get_offers=_handler)

    with app.test_client() as client:
        resp = client.get("/api/onliner-offers/abc")

    assert resp.status_code == 200
    assert resp.get_json() == {"id": "abc"}


def test_onliner_b2b_test_rejects_get():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/onliner-b2b-test")

    assert resp.status_code == 405
