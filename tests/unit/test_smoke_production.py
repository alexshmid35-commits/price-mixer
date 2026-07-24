import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "deploy" / "smoke_production.py"
SPEC = importlib.util.spec_from_file_location("smoke_production", MODULE_PATH)
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def _env(**overrides):
    values = {
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "long-enough-password",
        "PRICE_MIXER_SMOKE_URL": "http://127.0.0.1:5001",
    }
    values.update(overrides)
    return values


def test_smoke_requires_loopback_url():
    result = SMOKE.run_smoke(
        _env(PRICE_MIXER_SMOKE_URL="https://example.com")
    )

    assert result["status"] == "failed"
    assert result["checks"] == []


def test_smoke_checks_auth_request_id_version_and_worker():
    calls = []

    def requester(base_url, route, **kwargs):
        calls.append((base_url, route, kwargs))
        payloads = {
            "/api/health": {"status": "ok"},
            "/api/version": {"version": "2.0.0"},
            "/api/worker-status": {
                "mode": "external",
                "status": "ok",
                "active_workers": 1,
            },
        }
        return {
            "status": 401 if route == "/" else 200,
            "headers": {"x-request-id": kwargs["request_id"]},
            "json": payloads.get(route),
        }

    result = SMOKE.run_smoke(_env(), requester=requester)

    assert result["status"] == "passed"
    assert [item["status"] for item in result["checks"]] == ["passed"] * 4
    assert calls[0][2]["authenticated"] is False
    assert calls[1][2]["authenticated"] is False
    assert calls[2][2]["authenticated"] is True
    assert calls[3][2]["authenticated"] is True
    assert len({call[2]["request_id"] for call in calls}) == 1


def test_smoke_failure_output_does_not_include_credentials():
    def requester(_base_url, _route, **_kwargs):
        raise RuntimeError("connection failed")

    env = _env(ADMIN_PASSWORD="do-not-print-this-secret")
    result = SMOKE.run_smoke(env, requester=requester)

    assert result["status"] == "failed"
    assert env["ADMIN_PASSWORD"] not in str(result)


def test_smoke_can_accept_inline_worker_only_when_explicitly_requested():
    def requester(_base_url, route, **kwargs):
        payloads = {
            "/api/health": {"status": "ok"},
            "/api/version": {"version": "2.0.0"},
            "/api/worker-status": {
                "mode": "inline",
                "status": "ok",
                "active_workers": 0,
            },
        }
        return {
            "status": 401 if route == "/" else 200,
            "headers": {"x-request-id": kwargs["request_id"]},
            "json": payloads.get(route),
        }

    strict = SMOKE.run_smoke(_env(), requester=requester)
    local = SMOKE.run_smoke(
        _env(PRICE_MIXER_SMOKE_REQUIRE_WORKER="0"),
        requester=requester,
    )

    assert strict["status"] == "failed"
    assert local["status"] == "passed"
