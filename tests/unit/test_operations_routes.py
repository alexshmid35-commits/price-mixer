from flask import Flask

from price_mixer.api.operations_routes import create_operations_bp


def _app():
    app = Flask(__name__)
    app.register_blueprint(
        create_operations_bp(
            background_xlsx_status=lambda: {"state": "deferred"},
            worker_status=lambda: ({"status": "unavailable"}, 503),
            sorting_reparse_run=lambda: {"ok": True},
            sorting_reparse_run_all=lambda: ({"ok": False}, 400),
            sorting_reparse_status=lambda: {"ok": True, "done": 4},
            cancel_job=lambda job_id: {"status": "ok", "job_id": job_id},
            resume_job=lambda job_id: ({"status": "ok", "job_id": job_id}, 202),
        )
    )
    return app


def test_operations_blueprint_exposes_status_and_parser_routes():
    with _app().test_client() as client:
        assert client.get("/api/background-xlsx-status").get_json() == {"state": "deferred"}
        assert client.get("/api/worker-status").status_code == 503
        assert client.post("/api/sorting-reparse/run").get_json() == {"ok": True}
        assert client.post("/api/sorting-reparse/run-all").status_code == 400
        assert client.get("/api/sorting-reparse/status").get_json()["done"] == 4


def test_operations_blueprint_exposes_cancel_and_resume():
    with _app().test_client() as client:
        cancelled = client.post("/api/jobs/abc/cancel")
        resumed = client.post("/api/jobs/abc/resume")

    assert cancelled.get_json()["job_id"] == "abc"
    assert resumed.status_code == 202
