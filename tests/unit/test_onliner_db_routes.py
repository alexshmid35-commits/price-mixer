"""Unit tests for Onliner local database API blueprint."""

from io import BytesIO

from flask import Flask

from price_mixer.api.onliner_db_routes import create_onliner_db_bp


def _make_app(
    *,
    get_stats=None,
    search=None,
    rebuild=None,
    import_gsheet=None,
    import_csv=None,
    get_import_status=None,
    get_session=lambda: "/tmp/session",
):
    app = Flask(__name__)
    app.register_blueprint(create_onliner_db_bp(
        get_stats=get_stats or (lambda: {"products": 2}),
        search=search or (lambda query: {"items": [{"id": query}]}),
        rebuild=rebuild or (lambda session_dir: {"status": "ok", "session_dir": session_dir}),
        import_gsheet=import_gsheet or (lambda payload: {"status": "started", "payload": payload}),
        import_csv=import_csv or (lambda file: {"status": "started", "filename": file.filename if file else None}),
        get_import_status=get_import_status or (lambda: {"running": False}),
        get_active_session_dir=get_session,
    ))
    return app


def test_onliner_db_stats_disables_cache():
    app = _make_app(get_stats=lambda: {"products": 3, "names": 5})

    with app.test_client() as client:
        resp = client.get("/api/onliner-db-stats")

    assert resp.status_code == 200
    assert resp.get_json() == {"products": 3, "names": 5}
    assert resp.headers["Cache-Control"] == "no-store"


def test_onliner_db_search_skips_callback_for_empty_query():
    calls = []
    app = _make_app(search=lambda query: calls.append(query) or {"items": []})

    with app.test_client() as client:
        resp = client.get("/api/onliner-db-search?q=+")

    assert resp.status_code == 200
    assert resp.get_json() == {"items": []}
    assert calls == []


def test_onliner_db_search_propagates_callback_status():
    app = _make_app(search=lambda query: ({"items": [], "message": query}, 503))

    with app.test_client() as client:
        resp = client.get("/api/onliner-db-search?q=ssd")

    assert resp.status_code == 503
    assert resp.get_json() == {"items": [], "message": "ssd"}


def test_onliner_db_rebuild_passes_active_session():
    app = _make_app(get_session=lambda: "/tmp/active")

    with app.test_client() as client:
        resp = client.post("/api/onliner-db-rebuild")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "session_dir": "/tmp/active"}


def test_onliner_db_import_gsheet_passes_json_payload():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post("/api/onliner-db-import-gsheet", json={"sheet_id": "abc"})

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "started", "payload": {"sheet_id": "abc"}}


def test_onliner_db_import_csv_passes_uploaded_file():
    app = _make_app()

    with app.test_client() as client:
        resp = client.post(
            "/api/onliner-db-import-csv",
            data={"file": (BytesIO(b"id,name\n1,test\n"), "catalog.csv")},
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "started", "filename": "catalog.csv"}


def test_onliner_db_import_status_disables_cache():
    app = _make_app(get_import_status=lambda: {"running": True, "percent": 7})

    with app.test_client() as client:
        resp = client.get("/api/onliner-db-import-status")

    assert resp.status_code == 200
    assert resp.get_json() == {"running": True, "percent": 7}
    assert "no-cache" in resp.headers["Cache-Control"]
