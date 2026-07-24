"""Unit tests for export/download API blueprint."""

from flask import Flask, jsonify, redirect

from price_mixer.api.export_routes import create_export_bp


def _make_app(
    *,
    download=None,
    export_google_sheets=None,
    download_id_quality_report=None,
    download_id_compare_report=None,
    preexport_quality_check=None,
):
    app = Flask(__name__)
    app.register_blueprint(create_export_bp(
        download=download or (lambda: redirect("/")),
        export_google_sheets=export_google_sheets or (lambda: ({"status": "error"}, 400)),
        download_id_quality_report=download_id_quality_report or (lambda: jsonify({"status": "ok"})),
        download_id_compare_report=download_id_compare_report,
        preexport_quality_check=preexport_quality_check or (lambda: {"status": "ok", "checked": 0}),
    ))
    return app


def test_download_accepts_redirect_response():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/download")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_export_google_sheets_propagates_status():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/export-google-sheets", json={})

    assert resp.status_code == 400
    assert resp.get_json() == {"status": "error"}


def test_download_id_quality_report_accepts_flask_response():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/download/id-quality-report")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_download_id_compare_report_route_is_optional():
    app = _make_app(download_id_compare_report=lambda: jsonify({"status": "ok", "kind": "id_compare"}))

    with app.test_client() as client:
        resp = client.get("/download/id-compare-report")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "kind": "id_compare"}


def test_preexport_quality_check_returns_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/preexport-quality-check")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "checked": 0}


def test_export_google_sheets_rejects_get():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/export-google-sheets")

    assert resp.status_code == 405
