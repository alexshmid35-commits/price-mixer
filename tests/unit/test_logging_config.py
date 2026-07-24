import io
import json
import logging
import re

from flask import Flask

from price_mixer.logging_config import (
    configure_price_mixer_logging,
    get_logger,
    log_context,
    new_request_id,
    redact_text,
)
from price_mixer.request_logging import register_request_logging


def test_redact_text_masks_common_secret_shapes():
    rendered = redact_text(
        "Authorization: Bearer bearer-value "
        "password=pass-value api_key=key-value "
        "https://db-user:db-pass@example.test/path"
    )

    assert "bearer-value" not in rendered
    assert "pass-value" not in rendered
    assert "key-value" not in rendered
    assert "db-user" not in rendered
    assert "db-pass" not in rendered
    assert rendered.count("***") >= 4


def test_text_logging_adds_context_and_redacts_message():
    stream = io.StringIO()
    configure_price_mixer_logging(
        {"PRICE_MIXER_LOG_LEVEL": "INFO", "PRICE_MIXER_LOG_FORMAT": "text"},
        stream,
        force=True,
    )
    logger = get_logger("price_mixer.test")

    with log_context(request_id="request-123", job_id="job-456"):
        logger.info("request token=never-print-this")

    rendered = stream.getvalue()
    assert "request_id=request-123" in rendered
    assert "job_id=job-456" in rendered
    assert "never-print-this" not in rendered
    assert "token=***" in rendered


def test_json_logging_is_machine_readable_and_redacts_exceptions():
    stream = io.StringIO()
    configure_price_mixer_logging(
        {"PRICE_MIXER_LOG_LEVEL": "WARNING", "PRICE_MIXER_LOG_FORMAT": "json"},
        stream,
        force=True,
    )
    logger = get_logger("price_mixer.test")

    with log_context(request_id="json-request"):
        try:
            raise RuntimeError("password=exception-secret")
        except RuntimeError:
            logger.exception("operation failed api_key=message-secret")

    payload = json.loads(stream.getvalue())
    assert payload["level"] == "ERROR"
    assert payload["logger"] == "price_mixer.test"
    assert payload["request_id"] == "json-request"
    assert payload["job_id"] == "-"
    assert "message-secret" not in payload["message"]
    assert "exception-secret" not in payload["exception"]


def test_new_request_id_accepts_only_log_safe_values():
    assert new_request_id("caller.request-123") == "caller.request-123"

    generated = new_request_id("invalid id with spaces")
    assert generated != "invalid id with spaces"
    assert re.fullmatch(r"[0-9a-f]{32}", generated)


def test_log_context_replaces_unsafe_internal_correlation_ids():
    stream = io.StringIO()
    configure_price_mixer_logging(
        {"PRICE_MIXER_LOG_LEVEL": "INFO", "PRICE_MIXER_LOG_FORMAT": "text"},
        stream,
        force=True,
    )

    with log_context(request_id="unsafe\nrequest", job_id="unsafe\njob"):
        get_logger("price_mixer.test").info("safe")

    rendered = stream.getvalue()
    assert "unsafe" not in rendered
    assert re.search(r"request_id=[0-9a-f]{32}", rendered)
    assert re.search(r"job_id=[0-9a-f]{32}", rendered)


def test_request_logging_returns_correlation_header_and_safe_access_line():
    stream = io.StringIO()
    configure_price_mixer_logging(
        {"PRICE_MIXER_LOG_LEVEL": "INFO", "PRICE_MIXER_LOG_FORMAT": "text"},
        stream,
        force=True,
    )
    app = Flask(__name__)
    register_request_logging(app, get_logger("price_mixer.http_test"))

    @app.get("/example")
    def example():
        return {"ok": True}

    with app.test_client() as client:
        response = client.get(
            "/example?token=query-secret",
            headers={"X-Request-ID": "external-123"},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "external-123"
    rendered = stream.getvalue()
    assert "request_id=external-123" in rendered
    assert "method=GET path=/example status=200" in rendered
    assert "query-secret" not in rendered


def test_request_logging_replaces_unsafe_request_id_and_skips_health_access():
    stream = io.StringIO()
    configure_price_mixer_logging(
        {"PRICE_MIXER_LOG_LEVEL": "INFO", "PRICE_MIXER_LOG_FORMAT": "text"},
        stream,
        force=True,
    )
    app = Flask(__name__)
    register_request_logging(app, get_logger("price_mixer.http_test"))

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    with app.test_client() as client:
        response = client.get(
            "/api/health",
            headers={"X-Request-ID": "unsafe request id"},
        )

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])
    assert stream.getvalue() == ""


def teardown_module():
    # Leave the shared logger quiet for tests importing these modules later.
    logger = logging.getLogger("price_mixer")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logger.addHandler(logging.NullHandler())
