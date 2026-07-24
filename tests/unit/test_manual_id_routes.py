"""Unit tests for manual Onliner ID API blueprint."""

from flask import Flask

from price_mixer.api.manual_id_routes import create_manual_id_bp


def _make_app(
    *,
    get_session=lambda: "/tmp/session",
    confirm_batch=None,
    clear=None,
    reject_match=None,
    rollback_last=None,
):
    app = Flask(__name__)
    app.register_blueprint(create_manual_id_bp(
        get_active_session_dir=get_session,
        confirm_batch=confirm_batch or (lambda session_dir, payload: {"status": "ok", "session_dir": session_dir, "payload": payload}),
        clear=clear or (lambda session_dir, payload: {"status": "ok", "session_dir": session_dir, "payload": payload}),
        reject_match=reject_match or (lambda session_dir, payload: {"status": "ok", "session_dir": session_dir, "payload": payload}),
        rollback_last=rollback_last or (lambda session_dir: {"status": "ok", "session_dir": session_dir}),
    ))
    return app


def test_manual_id_confirm_batch_passes_session_and_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/manual-id-confirm-batch", json={"items": [{"row_idx": 1}]})

    assert resp.status_code == 200
    assert resp.get_json() == {
        "status": "ok",
        "session_dir": "/tmp/session",
        "payload": {"items": [{"row_idx": 1}]},
    }


def test_manual_id_confirm_batch_propagates_callback_status():
    app = _make_app(confirm_batch=lambda session_dir, payload: ({"status": "error"}, 409))

    with app.test_client() as client:
        resp = client.post("/api/manual-id-confirm-batch", json={"items": []})

    assert resp.status_code == 409
    assert resp.get_json() == {"status": "error"}


def test_manual_id_clear_passes_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/manual-id-clear", json={"item": {"name": "SSD"}})

    assert resp.status_code == 200
    assert resp.get_json()["payload"] == {"item": {"name": "SSD"}}


def test_manual_id_clear_uses_empty_payload_for_invalid_json():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/manual-id-clear", data="not-json", content_type="text/plain")

    assert resp.status_code == 200
    assert resp.get_json()["payload"] == {}


def test_manual_id_reject_match_propagates_callback_status():
    app = _make_app(reject_match=lambda session_dir, payload: ({"status": "error"}, 400))

    with app.test_client() as client:
        resp = client.post("/api/iven-reject-match", json={"name": "SSD"})

    assert resp.status_code == 400
    assert resp.get_json() == {"status": "error"}


def test_manual_id_rollback_last_passes_session():
    app = _make_app(get_session=lambda: "/tmp/rollback")

    with app.test_client() as client:
        resp = client.post("/api/manual-id-rollback-last")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "session_dir": "/tmp/rollback"}
