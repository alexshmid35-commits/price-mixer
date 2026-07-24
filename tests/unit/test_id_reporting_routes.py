"""Unit tests for Onliner ID reporting/search API blueprint."""

from flask import Flask

from price_mixer.api.id_reporting_routes import create_id_reporting_bp


def _make_app(
    *,
    replace_candidates=None,
    check_duplicate_ids=None,
    get_quality_report=None,
):
    app = Flask(__name__)
    app.register_blueprint(create_id_reporting_bp(
        replace_candidates=replace_candidates or (lambda payload: {"items": [], "payload": payload}),
        check_duplicate_ids=check_duplicate_ids or (lambda: {"status": "ok", "problem_rows": 0}),
        get_quality_report=get_quality_report or (lambda: {"status": "ok", "has_csv": False}),
    ))
    return app


def test_id_replace_candidates_passes_json_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/id-replace-candidates", json={"name": "SSD"})

    assert resp.status_code == 200
    assert resp.get_json() == {"items": [], "payload": {"name": "SSD"}}


def test_id_replace_candidates_uses_empty_payload_for_invalid_json():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/id-replace-candidates", data="bad", content_type="text/plain")

    assert resp.status_code == 200
    assert resp.get_json()["payload"] == {}


def test_id_replace_candidates_propagates_callback_status():
    app = _make_app(replace_candidates=lambda payload: ({"status": "error"}, 503))

    with app.test_client() as client:
        resp = client.post("/api/id-replace-candidates", json={})

    assert resp.status_code == 503
    assert resp.get_json() == {"status": "error"}


def test_check_duplicate_onliner_ids_returns_callback_payload():
    app = _make_app(check_duplicate_ids=lambda: {"status": "ok", "problem_ids": 2})

    with app.test_client() as client:
        resp = client.post("/api/check-duplicate-onliner-ids")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "problem_ids": 2}


def test_id_quality_report_returns_callback_payload():
    app = _make_app(get_quality_report=lambda: {"status": "not_found"})

    with app.test_client() as client:
        resp = client.get("/api/id-quality-report")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "not_found"}
