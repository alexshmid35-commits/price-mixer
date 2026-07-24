"""Unit tests for main page/upload/data API blueprint."""

from flask import Flask, jsonify, redirect

from price_mixer.api.main_routes import create_main_bp


def _make_app(
    *,
    index=None,
    result_page=None,
    upload=None,
    consolidated=None,
    consolidated_page=None,
    stats=None,
    export_row_indexes=None,
):
    app = Flask(__name__)
    app.register_blueprint(create_main_bp(
        index=index or (lambda: "upload page"),
        result_page=result_page or (lambda: redirect("/")),
        upload=upload or (lambda: ({"status": "error"}, 400)),
        consolidated=consolidated or (lambda: jsonify({"data": []})),
        consolidated_page=consolidated_page or (
            lambda: {"draw": 0, "recordsTotal": 0, "recordsFiltered": 0, "data": []}
        ),
        stats=stats or (lambda: {"without_id": 0, "duplicate_id_rows": 0, "export_rows": 0}),
        export_row_indexes=export_row_indexes or (lambda: {"indexes": [], "count": 0}),
    ))
    return app


def test_index_returns_page_response():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/")

    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "upload page"


def test_result_page_accepts_redirect_response():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/result")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_upload_propagates_status():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/upload")

    assert resp.status_code == 400
    assert resp.get_json() == {"status": "error"}


def test_consolidated_accepts_flask_response():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/consolidated")

    assert resp.status_code == 200
    assert resp.get_json() == {"data": []}


def test_consolidated_page_returns_server_side_payload():
    app = _make_app(consolidated_page=lambda: {
        "draw": 2,
        "recordsTotal": 10,
        "recordsFiltered": 3,
        "data": [["1", "SSD"]],
    })

    with app.test_client() as client:
        resp = client.get("/api/consolidated-page?draw=2")

    assert resp.status_code == 200
    assert resp.get_json()["recordsFiltered"] == 3


def test_stats_returns_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/api/stats")

    assert resp.status_code == 200
    assert resp.get_json() == {"without_id": 0, "duplicate_id_rows": 0, "export_rows": 0}


def test_export_row_indexes_returns_payload():
    app = _make_app(export_row_indexes=lambda: {"indexes": [1, 3], "count": 2})

    with app.test_client() as client:
        resp = client.get("/api/export-row-indexes")

    assert resp.status_code == 200
    assert resp.get_json() == {"indexes": [1, 3], "count": 2}


def test_upload_rejects_get():
    app = _make_app()

    with app.test_client() as client:
        resp = client.get("/upload")

    assert resp.status_code == 405
