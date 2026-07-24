import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from price_mixer.services.production_config import (
    require_valid_production_environment,
    validate_production_environment,
)


ROOT = Path(__file__).resolve().parents[2]


def _valid_environment():
    return {
        "PRICE_MIXER_ENV": "production",
        "PRICE_MIXER_BIND": "127.0.0.1:5001",
        "PRICE_MIXER_WORKERS": "1",
        "ADMIN_USERNAME": "price-admin",
        "ADMIN_PASSWORD": "a-long-admin-password",
        "FLASK_SECRET_KEY": "independent-flask-secret-key-value",
    }


def test_valid_production_environment_passes():
    environment = _valid_environment()

    assert validate_production_environment(environment) == []
    assert require_valid_production_environment(environment) is None


def test_production_environment_fails_closed_without_exposing_values():
    environment = {
        "PRICE_MIXER_ENV": "development",
        "PRICE_MIXER_BIND": "0.0.0.0:5001",
        "PRICE_MIXER_WORKERS": "4",
        "ADMIN_USERNAME": "",
        "ADMIN_PASSWORD": "secret-value",
        "FLASK_SECRET_KEY": "secret-value",
    }

    errors = validate_production_environment(environment)
    rendered = "\n".join(errors)

    assert "PRICE_MIXER_ENV" in rendered
    assert "PRICE_MIXER_BIND" in rendered
    assert "PRICE_MIXER_WORKERS" in rendered
    assert "ADMIN_USERNAME" in rendered
    assert "ADMIN_PASSWORD" in rendered
    assert "FLASK_SECRET_KEY" in rendered
    assert "secret-value" not in rendered


def test_production_environment_rejects_placeholders():
    environment = _valid_environment()
    environment["ADMIN_PASSWORD"] = "REPLACE_WITH_A_PASSWORD"

    errors = validate_production_environment(environment)

    assert errors == ["ADMIN_PASSWORD still contains a placeholder"]


def test_production_environment_rejects_unsafe_runtime_limits():
    environment = _valid_environment()
    environment.update(
        {
            "PRICE_MIXER_THREADS": "100",
            "PRICE_MIXER_REQUEST_TIMEOUT": "fast",
            "PRICE_MIXER_GRACEFUL_TIMEOUT": "5",
            "PRICE_MIXER_FORWARDED_ALLOW_IPS": "*",
        }
    )

    errors = validate_production_environment(environment)

    assert "PRICE_MIXER_THREADS must be between 1 and 16" in errors
    assert "PRICE_MIXER_REQUEST_TIMEOUT must be an integer" in errors
    assert (
        "PRICE_MIXER_GRACEFUL_TIMEOUT must be between 30 and 900"
        in errors
    )
    assert (
        "PRICE_MIXER_FORWARDED_ALLOW_IPS must not trust every address"
        in errors
    )


def test_production_environment_rejects_unsafe_runtime_directories():
    environment = _valid_environment()
    environment.update(
        {
            "PRICE_MIXER_STATE_DIR": "relative/state",
            "PRICE_MIXER_DATA_DIR": "/opt/price-mixer/current/data",
            "PRICE_MIXER_CACHE_DIR": "/var/lib/shared",
            "PRICE_MIXER_UPLOAD_DIR": "/var/lib/shared",
        }
    )

    errors = validate_production_environment(environment)

    assert "PRICE_MIXER_STATE_DIR must be an absolute path" in errors
    assert (
        "PRICE_MIXER_DATA_DIR must be outside the application directory"
        in errors
    )
    assert "PRICE_MIXER runtime directories must be distinct" in errors


def test_wsgi_entrypoint_validates_and_initializes_once(monkeypatch):
    calls = []
    fake_flask_app = SimpleNamespace(wsgi_app=lambda environ, start: [])
    fake_app_module = ModuleType("app")
    fake_app_module.app = fake_flask_app
    fake_app_module.init_onliner_db = lambda: calls.append("init")
    monkeypatch.setitem(sys.modules, "app", fake_app_module)
    for key, value in _valid_environment().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PRICE_MIXER_TRUST_PROXY", "0")

    namespace = runpy.run_path(str(ROOT / "wsgi.py"))

    assert namespace["application"] is fake_flask_app
    assert calls == ["init"]


def test_wsgi_entrypoint_rejects_invalid_environment_before_db_init(
    monkeypatch,
):
    calls = []
    fake_app_module = ModuleType("app")
    fake_app_module.app = SimpleNamespace(
        wsgi_app=lambda environ, start: []
    )
    fake_app_module.init_onliner_db = lambda: calls.append("init")
    monkeypatch.setitem(sys.modules, "app", fake_app_module)
    monkeypatch.setenv("PRICE_MIXER_ENV", "development")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Invalid production"):
        runpy.run_path(str(ROOT / "wsgi.py"))

    assert calls == []


def test_gunicorn_profile_is_single_worker_and_loopback(monkeypatch):
    monkeypatch.setenv("PRICE_MIXER_THREADS", "6")
    namespace = runpy.run_path(
        str(ROOT / "deploy" / "gunicorn.conf.py")
    )

    assert namespace["bind"] == "127.0.0.1:5001"
    assert namespace["workers"] == 1
    assert namespace["worker_class"] == "gthread"
    assert namespace["threads"] == 6
    assert namespace["preload_app"] is False
    assert namespace["daemon"] is False
    assert namespace["accesslog"] is None


def test_deployment_templates_are_safe_and_complete():
    service = (
        ROOT / "deploy" / "price-mixer.service"
    ).read_text(encoding="utf-8")
    nginx = (
        ROOT / "deploy" / "nginx-price-mixer.conf"
    ).read_text(encoding="utf-8")
    environment = (
        ROOT / "deploy" / "price-mixer.env.example"
    ).read_text(encoding="utf-8")
    requirements = (
        ROOT / "requirements-prod.txt"
    ).read_text(encoding="utf-8")
    runbook = (
        ROOT / "PRODUCTION_DEPLOYMENT.md"
    ).read_text(encoding="utf-8")

    assert "deploy/check_production.py" in service
    assert "wsgi:application" in service
    assert "Restart=on-failure" in service
    assert "ReadOnlyPaths=/opt/price-mixer/current" in service
    assert "ReadWritePaths=/var/lib/price-mixer/state" in service
    assert "proxy_pass http://127.0.0.1:5001" in nginx
    assert "client_max_body_size 200m" in nginx
    assert "log_format price_mixer_safe" in nginx
    assert "$request_method $uri $server_protocol" in nginx
    assert "$request_method $request_uri" not in nginx
    assert "PRICE_MIXER_WORKERS=1" in environment
    assert "PRICE_MIXER_STATE_DIR=/var/lib/price-mixer/state" in environment
    assert "PRICE_MIXER_JOB_MODE=external" in environment
    assert "price-mixer-worker.service" in service
    assert "REPLACE_WITH_A_LONG_RANDOM_PASSWORD" in environment
    assert "gunicorn[gthread]==26.0.0" in requirements
    assert "одним Gunicorn worker" in runbook
    assert "ai2025-" not in environment
