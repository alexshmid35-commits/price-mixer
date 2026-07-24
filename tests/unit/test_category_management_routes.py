"""Unit tests for category management API blueprint."""

from flask import Flask, jsonify

from price_mixer.api.category_management_routes import create_category_management_bp


def _make_app(*, handlers=None):
    app = Flask(__name__)
    app.register_blueprint(create_category_management_bp(
        handlers=handlers or {
            "/api/category-visibility": (lambda: {"status": "ok", "name": "visibility"}, ("POST",)),
            "/api/apply-markup": (lambda: ({"status": "error"}, 400), ("POST",)),
            "/api/category-override-items": (lambda: {"items": []}, ("GET",)),
        },
    ))
    return app


def test_category_management_post_handler_returns_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/category-visibility", json={"supplier": "N-Tech"})

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "name": "visibility"}


def test_category_management_handler_propagates_status():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/apply-markup", json={})

    assert resp.status_code == 400
    assert resp.get_json() == {"status": "error"}


def test_category_management_get_handler_returns_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/category-override-items")

    assert resp.status_code == 200
    assert resp.get_json() == {"items": []}


def test_category_management_accepts_flask_response():
    def _handler():
        return jsonify({"status": "ok"})

    app = _make_app(handlers={"/api/markup-preview": (_handler, ("POST",))})

    with app.test_client() as client:
        resp = client.post("/api/markup-preview")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_category_management_rejects_wrong_method():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/category-visibility")

    assert resp.status_code == 405


def test_category_management_supports_second_blueprint_name():
    app = Flask(__name__)
    app.register_blueprint(create_category_management_bp(
        handlers={"/api/category-visibility": (lambda: {"status": "ok"}, ("POST",))},
    ))
    app.register_blueprint(create_category_management_bp(
        name="category_management_extra_api",
        handlers={"/api/category-markups": (lambda: {"markups": {}}, ("GET",))},
    ))

    with app.test_client() as client:
        resp = client.get("/api/category-markups")

    assert resp.status_code == 200
    assert resp.get_json() == {"markups": {}}
