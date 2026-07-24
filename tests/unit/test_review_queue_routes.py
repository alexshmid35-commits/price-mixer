"""Unit tests for manual review queue API blueprint."""

from flask import Flask, jsonify

from price_mixer.api.review_queue_routes import create_review_queue_bp


def _make_app(
    *,
    start_handlers=None,
    list_queue=None,
    pick=None,
    clear=None,
):
    app = Flask(__name__)
    app.register_blueprint(create_review_queue_bp(
        start_handlers=start_handlers or {
            "/api/cpu-review-queue-start": lambda: {"status": "started", "kind": "cpu"},
            "/api/gpu-review-queue-start": lambda: ({"status": "error"}, 409),
        },
        list_queue=list_queue or (lambda: {"items": []}),
        pick=pick or (lambda: {"status": "ok", "remaining": 0}),
        clear=clear or (lambda: {"status": "ok"}),
    ))
    return app


def test_review_queue_start_handler_returns_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/cpu-review-queue-start")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "started", "kind": "cpu"}


def test_review_queue_start_handler_propagates_status():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/gpu-review-queue-start")

    assert resp.status_code == 409
    assert resp.get_json() == {"status": "error"}


def test_review_queue_returns_items():
    app = _make_app(list_queue=lambda: {"items": [{"name_key": "ssd"}]})

    with app.test_client() as client:
        resp = client.get("/api/review-queue")

    assert resp.status_code == 200
    assert resp.get_json() == {"items": [{"name_key": "ssd"}]}


def test_review_queue_pick_returns_callback_payload():
    app = _make_app(pick=lambda: {"status": "ok", "remaining": 2})

    with app.test_client() as client:
        resp = client.post("/api/review-queue-pick", json={"name_key": "ssd"})

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "remaining": 2}


def test_review_queue_clear_accepts_flask_response():
    def _clear():
        return jsonify({"status": "ok"})

    app = _make_app(clear=_clear)

    with app.test_client() as client:
        resp = client.post("/api/review-queue-clear")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
