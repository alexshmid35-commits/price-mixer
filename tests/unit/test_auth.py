"""Unit tests for HTTP Basic Auth."""

import pytest

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


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
    from config import cfg
    resp = client.get("/", headers={
        "Authorization": "Basic " + __import__("base64").b64encode(f"{cfg.admin_username}:{cfg.admin_password}".encode()).decode()
    })
    assert resp.status_code in (200, 302)  # 302 redirect if no active session
