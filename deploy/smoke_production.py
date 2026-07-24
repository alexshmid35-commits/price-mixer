"""Authenticated loopback smoke check without exposing secrets or bodies."""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def validate_base_url(value):
    parsed = urllib.parse.urlsplit(str(value or "").strip())
    if parsed.scheme != "http":
        return "smoke URL must use HTTP on loopback"
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return "smoke URL must use a loopback host"
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return "smoke URL must not contain credentials, query, or fragment"
    if parsed.path not in {"", "/"}:
        return "smoke URL must not contain a path"
    try:
        port = parsed.port
    except ValueError:
        return "smoke URL port is invalid"
    if not port:
        return "smoke URL must include a port"
    return ""


def run_smoke(environ=None, *, requester=None):
    env = os.environ if environ is None else environ
    base_url = str(
        env.get("PRICE_MIXER_SMOKE_URL", "http://127.0.0.1:5001")
        or ""
    ).rstrip("/")
    base_error = validate_base_url(base_url)
    if base_error:
        return {"status": "failed", "checks": [], "errors": [base_error]}

    username = str(env.get("ADMIN_USERNAME", "") or "")
    password = str(env.get("ADMIN_PASSWORD", "") or "")
    if not username or not password:
        return {
            "status": "failed",
            "checks": [],
            "errors": ["ADMIN_USERNAME and ADMIN_PASSWORD are required"],
        }

    request_fn = requester or _request
    require_external_worker = str(
        env.get("PRICE_MIXER_SMOKE_REQUIRE_WORKER", "1") or "1"
    ).strip().casefold() not in {"0", "false", "no", "off"}
    request_id = f"production-smoke-{uuid.uuid4().hex[:16]}"
    checks = []
    errors = []

    def check(label, route, expected_status, *, authenticated, validator=None):
        try:
            result = request_fn(
                base_url,
                route,
                username=username,
                password=password,
                authenticated=authenticated,
                request_id=request_id,
            )
            passed = result["status"] == expected_status
            if passed and validator is not None:
                passed = bool(validator(result))
        except Exception:
            passed = False
        checks.append({"name": label, "status": "passed" if passed else "failed"})
        if not passed:
            errors.append(f"{label} failed")

    check(
        "health",
        "/api/health",
        200,
        authenticated=False,
        validator=lambda result: (
            (result.get("json") or {}).get("status") == "ok"
            and result["headers"].get("x-request-id") == request_id
        ),
    )
    check("authentication_required", "/", 401, authenticated=False)
    check(
        "version",
        "/api/version",
        200,
        authenticated=True,
        validator=lambda result: bool((result.get("json") or {}).get("version")),
    )
    check(
        "durable_worker",
        "/api/worker-status",
        200,
        authenticated=True,
        validator=lambda result: (
            (
                (
                    (result.get("json") or {}).get("mode") == "external"
                    and int(
                        (result.get("json") or {}).get("active_workers", 0)
                    )
                    >= 1
                )
                if require_external_worker
                else (result.get("json") or {}).get("mode")
                in {"inline", "external"}
            )
            and (result.get("json") or {}).get("status") == "ok"
        ),
    )
    return {
        "status": "passed" if not errors else "failed",
        "checks": checks,
        "errors": errors,
    }


def _request(
    base_url,
    route,
    *,
    username,
    password,
    authenticated,
    request_id,
):
    headers = {
        "Accept": "application/json",
        "X-Request-ID": request_id,
    }
    if authenticated:
        token = base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    request = urllib.request.Request(
        f"{base_url}{route}",
        headers=headers,
        method="GET",
    )
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        body = response.read(1024 * 1024)
        response_headers = {
            str(key).casefold(): str(value)
            for key, value in response.headers.items()
        }
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        return {
            "status": int(response.status),
            "headers": response_headers,
            "json": payload,
        }


def main():
    result = run_smoke()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
