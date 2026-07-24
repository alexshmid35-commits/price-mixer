"""Unit tests for Onliner ID verification/validation API blueprint."""

from flask import Flask

from price_mixer.api.id_validation_routes import create_id_validation_bp


def _make_app(
    *,
    verify_all_start=None,
    get_verify_all_status=None,
    validate_clean_start=None,
    validate_clean_db_start=None,
    validate_clean_cancel=None,
    get_validate_clean_status=None,
):
    app = Flask(__name__)
    app.register_blueprint(create_id_validation_bp(
        verify_all_start=verify_all_start or (lambda: {"status": "started"}),
        get_verify_all_status=get_verify_all_status or (lambda: {"running": False, "items": []}),
        validate_clean_start=validate_clean_start or (lambda: {"status": "started", "mode": "api"}),
        validate_clean_db_start=validate_clean_db_start or (lambda: {"status": "started", "mode": "db"}),
        validate_clean_cancel=validate_clean_cancel or (lambda: {"status": "cancelling"}),
        get_validate_clean_status=get_validate_clean_status or (lambda: {"running": False, "mode": "api"}),
    ))
    return app


def test_verify_all_ids_start_returns_callback_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/verify-all-ids-start")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "started"}


def test_verify_all_ids_start_propagates_callback_status():
    app = _make_app(verify_all_start=lambda: ({"status": "error"}, 400))

    with app.test_client() as client:
        resp = client.post("/api/verify-all-ids-start")

    assert resp.status_code == 400
    assert resp.get_json() == {"status": "error"}


def test_verify_all_ids_status_returns_snapshot():
    app = _make_app(get_verify_all_status=lambda: {"running": True, "items": [{"id": "1"}]})

    with app.test_client() as client:
        resp = client.get("/api/verify-all-ids-status")

    assert resp.status_code == 200
    assert resp.get_json() == {"running": True, "items": [{"id": "1"}]}


def test_validate_clean_ids_start_returns_api_mode_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/validate-clean-ids-start")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "started", "mode": "api"}


def test_validate_clean_ids_db_start_returns_db_mode_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/validate-clean-ids-db-start")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "started", "mode": "db"}


def test_validate_clean_ids_status_returns_snapshot():
    app = _make_app(get_validate_clean_status=lambda: {"running": True, "mode": "db"})

    with app.test_client() as client:
        resp = client.get("/api/validate-clean-ids-status")

    assert resp.status_code == 200
    assert resp.get_json() == {"running": True, "mode": "db"}


def test_validate_clean_ids_cancel_returns_callback_payload():
    app = _make_app(validate_clean_cancel=lambda: {"status": "cancelling", "message": "Останавливаю проверку..."})

    with app.test_client() as client:
        resp = client.post("/api/validate-clean-ids-cancel")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "cancelling", "message": "Останавливаю проверку..."}


def test_validate_clean_ids_cancel_rejects_get():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/validate-clean-ids-cancel")

    assert resp.status_code == 405
