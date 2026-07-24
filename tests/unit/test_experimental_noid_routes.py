"""HTTP contracts for the experimental no-ID review API."""

from flask import Flask

from price_mixer.api.experimental_noid_routes import create_experimental_noid_bp


class RuntimeStub:
    def quality(self, session_dir, job_id):
        return {
            "ok": True,
            "job_id": job_id,
            "session_dir": session_dir,
            "overall": {"precision": 1.0},
        }


def test_quality_route_uses_active_session_and_job_id():
    app = Flask(__name__)
    app.register_blueprint(create_experimental_noid_bp(
        get_active_session_dir=lambda: "/tmp/session-1",
        get_runtime=lambda: RuntimeStub(),
    ))

    response = app.test_client().get(
        "/api/experimental-noid/quality?job_id=job-7"
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "job_id": "job-7",
        "session_dir": "/tmp/session-1",
        "overall": {"precision": 1.0},
    }
