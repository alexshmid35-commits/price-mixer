"""Unit tests for HTTP Basic Auth."""

import base64

import pytest

from app import STATIC_ASSETS, app


@pytest.fixture
def client():
    old_username = app.config.get("ADMIN_USERNAME")
    old_password = app.config.get("ADMIN_PASSWORD")
    app.config["TESTING"] = True
    app.config["ADMIN_USERNAME"] = "admin"
    app.config["ADMIN_PASSWORD"] = "test-password"
    with app.test_client() as client:
        yield client
    if old_username is None:
        app.config.pop("ADMIN_USERNAME", None)
    else:
        app.config["ADMIN_USERNAME"] = old_username
    if old_password is None:
        app.config.pop("ADMIN_PASSWORD", None)
    else:
        app.config["ADMIN_PASSWORD"] = old_password


def test_health_no_auth(client):
    """Health endpoint should be accessible without auth."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_version_no_auth(client):
    """Version endpoint should be accessible without auth."""
    resp = client.get("/api/version")
    assert resp.status_code == 200
    assert "version" in resp.get_json()


def test_index_requires_auth(client):
    """Index should require auth."""
    resp = client.get("/")
    assert resp.status_code == 401


def test_index_with_valid_auth(client):
    """Index should be accessible with valid credentials."""
    token = base64.b64encode(b"admin:test-password").decode()
    resp = client.get("/", headers={"Authorization": "Basic " + token})
    assert resp.status_code in (200, 302)  # 302 redirect if no active session


def test_versioned_static_asset_gets_immutable_cache(client):
    token = base64.b64encode(b"admin:test-password").decode()
    headers = {"Authorization": "Basic " + token}
    version = STATIC_ASSETS.version("css/result.css")

    versioned = client.get(
        f"/static/css/result.css?v={version}",
        headers=headers,
    )
    unversioned = client.get("/static/css/result.css", headers=headers)

    assert versioned.status_code == 200
    assert versioned.headers["Cache-Control"] == ("public, max-age=31536000, immutable")
    assert unversioned.headers["Cache-Control"] == "public, max-age=300"
