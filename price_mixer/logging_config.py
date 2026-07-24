"""Safe, structured logging helpers for Price Mixer."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone


_REQUEST_ID = ContextVar("price_mixer_request_id", default="-")
_JOB_ID = ContextVar("price_mixer_job_id", default="-")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_AUTH_RE = re.compile(
    r"(?i)\b(authorization\s*[:=]\s*)(basic|bearer)\s+[^\s,;]+"
)
_SECRET_RE = re.compile(
    r"""(?ix)
    (["']?(?:password|passwd|token|api[_-]?key|client[_-]?secret|secret)["']?)
    (\s*[:=]\s*)
    (["']?)[^\s,;&"']+(["']?)
    """
)
_URL_CREDENTIALS_RE = re.compile(r"(://)[^/\s:@]+:[^/\s@]+@")
_MANAGED_HANDLER_ATTR = "_price_mixer_managed_handler"


def redact_text(value) -> str:
    """Return a log-safe string with common credential shapes masked."""
    text = str(value)
    text = _AUTH_RE.sub(lambda match: f"{match.group(1)}{match.group(2)} ***", text)
    text = _SECRET_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{match.group(3)}***{match.group(4)}",
        text,
    )
    return _URL_CREDENTIALS_RE.sub(r"\1***:***@", text)


def new_request_id(candidate="") -> str:
    """Keep a safe caller-provided request ID or generate a new one."""
    return _new_correlation_id(candidate)


def new_job_id(candidate="") -> str:
    """Keep a safe job ID or generate a new one."""
    return _new_correlation_id(candidate)


def _new_correlation_id(candidate):
    normalized = str(candidate or "").strip()
    if _REQUEST_ID_RE.fullmatch(normalized):
        return normalized
    return uuid.uuid4().hex


def get_request_id() -> str:
    return _REQUEST_ID.get()


def get_job_id() -> str:
    return _JOB_ID.get()


def set_log_context(*, request_id=None, job_id=None):
    """Set selected context fields and return tokens suitable for reset."""
    tokens = {}
    if request_id is not None:
        tokens["request_id"] = _REQUEST_ID.set(new_request_id(request_id))
    if job_id is not None:
        tokens["job_id"] = _JOB_ID.set(new_job_id(job_id))
    return tokens


def reset_log_context(tokens) -> None:
    """Restore context fields previously changed by :func:`set_log_context`."""
    if not isinstance(tokens, dict):
        return
    if "job_id" in tokens:
        _JOB_ID.reset(tokens["job_id"])
    if "request_id" in tokens:
        _REQUEST_ID.reset(tokens["request_id"])


@contextmanager
def log_context(*, request_id=None, job_id=None):
    """Temporarily attach request/job correlation fields to log records."""
    tokens = set_log_context(request_id=request_id, job_id=job_id)
    try:
        yield
    finally:
        reset_log_context(tokens)


class _ContextFilter(logging.Filter):
    def filter(self, record):
        record.request_id = get_request_id()
        record.job_id = get_job_id()
        return True


class _SafeTextFormatter(logging.Formatter):
    def format(self, record):
        rendered = super().format(record)
        return redact_text(rendered)


class _SafeJsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "job_id": getattr(record, "job_id", "-"),
            "message": redact_text(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def get_logger(name: str) -> logging.Logger:
    """Return a Price Mixer logger without falling through to lastResort."""
    parent = logging.getLogger("price_mixer")
    parent.propagate = False
    if not parent.handlers:
        handler = logging.NullHandler()
        setattr(handler, _MANAGED_HANDLER_ATTR, True)
        parent.addHandler(handler)
    return logging.getLogger(name)


def configure_price_mixer_logging(environ=None, stream=None, *, force=False):
    """Configure the isolated ``price_mixer`` logger hierarchy."""
    env = os.environ if environ is None else environ
    logger = logging.getLogger("price_mixer")
    logger.propagate = False
    managed_handlers = [
        handler
        for handler in logger.handlers
        if getattr(handler, _MANAGED_HANDLER_ATTR, False)
    ]
    active_handlers = [
        handler for handler in managed_handlers if not isinstance(handler, logging.NullHandler)
    ]
    if active_handlers and not force:
        return logger
    for handler in managed_handlers:
        logger.removeHandler(handler)

    level_name = str(env.get("PRICE_MIXER_LOG_LEVEL", "INFO") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    format_name = str(env.get("PRICE_MIXER_LOG_FORMAT", "text") or "text").lower()
    handler = logging.StreamHandler(stream or sys.stderr)
    setattr(handler, _MANAGED_HANDLER_ATTR, True)
    handler.addFilter(_ContextFilter())
    if format_name == "json":
        handler.setFormatter(_SafeJsonFormatter())
    else:
        handler.setFormatter(
            _SafeTextFormatter(
                "%(asctime)s %(levelname)s %(name)s "
                "request_id=%(request_id)s job_id=%(job_id)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
    handler.setLevel(level)
    logger.addHandler(handler)
    logger.setLevel(level)
    return logger
