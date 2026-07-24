"""Onliner public API gateway with proxy routing and retry state."""

import threading
import time
from urllib.parse import urlsplit

import requests

from price_mixer.logging_config import get_logger
from price_mixer.settings import _coerce_bool, _coerce_float, _coerce_int, load_onliner_api_settings

LOGGER = get_logger("price_mixer.external.onliner")
ONLINER_API_SESSION_LOCAL = threading.local()
ONLINER_API_PROXY_STATE_LOCK = threading.RLock()
ONLINER_API_RETRY_STATUSES = {403, 408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 524}
ONLINER_API_PROXY_STATE = {}


def _get_session():
    session_obj = getattr(ONLINER_API_SESSION_LOCAL, "session", None)
    if session_obj is None:
        session_obj = requests.Session()
        session_obj.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        adapter = requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32)
        session_obj.mount("http://", adapter)
        session_obj.mount("https://", adapter)
        ONLINER_API_SESSION_LOCAL.session = session_obj
    return session_obj


def _route_key(route):
    if not route:
        return "direct"
    return str(route.get("key") or route.get("label") or "proxy").strip() or "proxy"


def _get_routes(settings):
    routes = []
    if _coerce_bool(settings.get("allow_direct", True), default=True):
        routes.append(None)
    routes.extend(list(settings.get("proxy_pool") or []))

    now = time.time()
    with ONLINER_API_PROXY_STATE_LOCK:
        def _rank(route):
            key = _route_key(route)
            state = ONLINER_API_PROXY_STATE.get(key, {})
            blocked_until = float(state.get("blocked_until", 0.0) or 0.0)
            failures = int(state.get("failures", 0) or 0)
            available = 0 if blocked_until <= now else 1
            return (available, blocked_until, failures, key)

        return sorted(routes, key=_rank)


def _mark_route_success(route):
    key = _route_key(route)
    with ONLINER_API_PROXY_STATE_LOCK:
        state = ONLINER_API_PROXY_STATE.setdefault(key, {})
        state["blocked_until"] = 0.0
        state["last_error"] = ""
        state["last_status"] = 200
        state["successes"] = int(state.get("successes", 0) or 0) + 1
        state["failures"] = 0
        state["updated_at"] = time.time()


def _mark_route_failure(route, reason, cooldown_sec, status_code=0):
    key = _route_key(route)
    with ONLINER_API_PROXY_STATE_LOCK:
        state = ONLINER_API_PROXY_STATE.setdefault(key, {})
        state["blocked_until"] = time.time() + max(0, int(cooldown_sec or 0))
        state["last_error"] = str(reason or "").strip()
        state["last_status"] = int(status_code or 0)
        state["failures"] = int(state.get("failures", 0) or 0) + 1
        state["updated_at"] = time.time()


def onliner_api_get(url, timeout=8, headers=None):
    settings = load_onliner_api_settings()
    routes = _get_routes(settings)
    if not routes:
        routes = [None]

    max_attempts = max(1, min(len(routes), _coerce_int(settings.get("retry_attempts", 3), 3, min_value=1, max_value=12)))
    cooldown_sec = _coerce_int(settings.get("proxy_cooldown_sec", 180), 180, min_value=10, max_value=3600)
    backoff_sec = _coerce_float(settings.get("backoff_sec", 0.6), 0.6, min_value=0.0, max_value=5.0)
    merged_headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    if isinstance(headers, dict):
        merged_headers.update(headers)

    last_response = None
    last_error = None
    session_obj = _get_session()
    endpoint_host = urlsplit(str(url or "")).hostname or "unknown"
    for attempt_index, route in enumerate(routes[:max_attempts]):
        try:
            response = session_obj.get(
                url,
                timeout=timeout,
                headers=merged_headers,
                proxies=(route or {}).get("proxies") if route else None,
            )
            if response.ok:
                _mark_route_success(route)
                return response
            last_response = response
            if int(response.status_code or 0) in ONLINER_API_RETRY_STATUSES and attempt_index + 1 < max_attempts:
                _mark_route_failure(route, f"http_{response.status_code}", cooldown_sec, status_code=response.status_code)
                LOGGER.warning(
                    "Onliner API retry host=%s status=%s attempt=%s/%s",
                    endpoint_host,
                    response.status_code,
                    attempt_index + 1,
                    max_attempts,
                )
                if backoff_sec > 0:
                    time.sleep(backoff_sec * (attempt_index + 1))
                continue
            return response
        except Exception as exc:
            last_error = exc
            _mark_route_failure(route, exc.__class__.__name__, cooldown_sec)
            LOGGER.warning(
                "Onliner API request failed host=%s error_type=%s attempt=%s/%s",
                endpoint_host,
                type(exc).__name__,
                attempt_index + 1,
                max_attempts,
            )
            if attempt_index + 1 < max_attempts and backoff_sec > 0:
                time.sleep(backoff_sec * (attempt_index + 1))

    if last_response is not None:
        return last_response
    raise last_error if last_error is not None else RuntimeError("onliner_api_get_failed")
