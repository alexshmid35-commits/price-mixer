"""Unit tests for bulk Onliner ID cleanup API blueprint."""

from flask import Flask

from price_mixer.api.bulk_id_routes import create_bulk_id_bp


def _make_app(
    *,
    get_session=lambda: "/tmp/session",
    clear_invalid=None,
    clear_all_nonpc=None,
    clear_ntech_duplicates=None,
):
    app = Flask(__name__)
    app.register_blueprint(create_bulk_id_bp(
        get_active_session_dir=get_session,
        clear_invalid=clear_invalid or (lambda session_dir, payload: {"status": "ok", "session_dir": session_dir, "payload": payload}),
        clear_all_nonpc=clear_all_nonpc or (lambda session_dir: {"status": "ok", "session_dir": session_dir}),
        clear_ntech_duplicates=clear_ntech_duplicates or (lambda session_dir: {"status": "ok", "session_dir": session_dir}),
    ))
    return app


def test_clear_invalid_onliner_ids_passes_session_and_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/clear-invalid-onliner-ids", json={"items": [{"onliner_id": "123"}]})

    assert resp.status_code == 200
    assert resp.get_json() == {
        "status": "ok",
        "session_dir": "/tmp/session",
        "payload": {"items": [{"onliner_id": "123"}]},
    }


def test_clear_invalid_onliner_ids_uses_empty_payload_for_invalid_json():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/clear-invalid-onliner-ids", data="bad", content_type="text/plain")

    assert resp.status_code == 200
    assert resp.get_json()["payload"] == {}


def test_clear_invalid_onliner_ids_propagates_callback_status():
    app = _make_app(clear_invalid=lambda session_dir, payload: ({"status": "error"}, 422))

    with app.test_client() as client:
        resp = client.post("/api/clear-invalid-onliner-ids", json={"items": []})

    assert resp.status_code == 422
    assert resp.get_json() == {"status": "error"}


def test_clear_all_nonpc_onliner_ids_passes_session():
    app = _make_app(get_session=lambda: "/tmp/nonpc")

    with app.test_client() as client:
        resp = client.post("/api/clear-all-nonpc-onliner-ids")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "session_dir": "/tmp/nonpc"}


def test_clear_ntech_duplicate_onliner_ids_passes_session():
    app = _make_app(get_session=lambda: "/tmp/duplicates")

    with app.test_client() as client:
        resp = client.post("/api/clear-ntech-duplicate-onliner-ids")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "session_dir": "/tmp/duplicates"}
