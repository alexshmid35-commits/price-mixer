"""Flask request correlation and access/error logging."""

from __future__ import annotations

import time

from flask import g, request

from price_mixer.logging_config import (
    get_logger,
    new_request_id,
    reset_log_context,
    set_log_context,
)


def register_request_logging(app, logger=None):
    """Register request ID and safe access logging hooks once per Flask app."""
    if app.extensions.get("price_mixer_request_logging"):
        return
    app.extensions["price_mixer_request_logging"] = True
    access_logger = logger or get_logger("price_mixer.http")

    @app.before_request
    def _begin_request_logging():
        request_id = new_request_id(request.headers.get("X-Request-ID", ""))
        g.price_mixer_request_id = request_id
        g.price_mixer_log_tokens = set_log_context(request_id=request_id)
        g.price_mixer_request_started = time.perf_counter()

    @app.after_request
    def _finish_request_logging(response):
        request_id = getattr(g, "price_mixer_request_id", new_request_id())
        response.headers["X-Request-ID"] = request_id
        if _should_log_access(request.path):
            started = getattr(g, "price_mixer_request_started", time.perf_counter())
            duration_ms = max(0.0, (time.perf_counter() - started) * 1000)
            access_logger.info(
                "request completed method=%s path=%s status=%s duration_ms=%.1f",
                request.method,
                request.path,
                response.status_code,
                duration_ms,
            )
        return response

    @app.teardown_request
    def _close_request_logging(error):
        try:
            if error is not None:
                access_logger.error(
                    "request failed method=%s path=%s",
                    request.method,
                    request.path,
                    exc_info=(type(error), error, error.__traceback__),
                )
        finally:
            tokens = getattr(g, "price_mixer_log_tokens", None)
            g.price_mixer_log_tokens = None
            reset_log_context(tokens)


def _should_log_access(path):
    return path != "/api/health" and not path.startswith("/static/")
