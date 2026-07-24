"""Validation helpers for the single-worker production profile."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath


PLACEHOLDER_TOKENS = (
    "change_me",
    "changeme",
    "replace_me",
    "replace-with",
    "replace_with",
)


def _is_placeholder(value):
    text = str(value or "").strip().casefold()
    return any(token in text for token in PLACEHOLDER_TOKENS)


def _secret_error(environ, key, *, min_length):
    value = str(environ.get(key, "") or "").strip()
    if not value:
        return f"{key} is required"
    if _is_placeholder(value):
        return f"{key} still contains a placeholder"
    if len(value) < int(min_length):
        return f"{key} must contain at least {int(min_length)} characters"
    return None


def _integer_setting_error(
    environ,
    key,
    *,
    default,
    minimum,
    maximum,
):
    text = str(environ.get(key, default) or default).strip()
    try:
        value = int(text)
    except ValueError:
        return f"{key} must be an integer"
    if value < int(minimum) or value > int(maximum):
        return (
            f"{key} must be between {int(minimum)} and "
            f"{int(maximum)}"
        )
    return None


def validate_production_environment(
    environ: Mapping[str, str],
) -> list[str]:
    """Return safe validation errors without exposing secret values."""
    errors = []
    if str(environ.get("PRICE_MIXER_ENV", "") or "").strip().casefold() != (
        "production"
    ):
        errors.append("PRICE_MIXER_ENV must be set to production")

    for key, min_length in (
        ("ADMIN_PASSWORD", 12),
        ("FLASK_SECRET_KEY", 32),
    ):
        error = _secret_error(environ, key, min_length=min_length)
        if error:
            errors.append(error)

    admin_username = str(
        environ.get("ADMIN_USERNAME", "") or ""
    ).strip()
    if not admin_username:
        errors.append("ADMIN_USERNAME is required")

    workers_text = str(
        environ.get("PRICE_MIXER_WORKERS", "1") or "1"
    ).strip()
    try:
        workers = int(workers_text)
    except ValueError:
        workers = 0
    if workers != 1:
        errors.append(
            "PRICE_MIXER_WORKERS must be 1 until background jobs "
            "and status storage are externalized"
        )

    for key, default, minimum, maximum in (
        ("PRICE_MIXER_THREADS", 4, 1, 16),
        ("PRICE_MIXER_REQUEST_TIMEOUT", 900, 30, 3600),
        ("PRICE_MIXER_GRACEFUL_TIMEOUT", 120, 30, 900),
    ):
        error = _integer_setting_error(
            environ,
            key,
            default=default,
            minimum=minimum,
            maximum=maximum,
        )
        if error:
            errors.append(error)

    bind = str(
        environ.get("PRICE_MIXER_BIND", "127.0.0.1:5001") or ""
    ).strip()
    if not (
        bind.startswith("127.0.0.1:")
        or bind.startswith("localhost:")
        or bind.startswith("unix:")
    ):
        errors.append(
            "PRICE_MIXER_BIND must use loopback or a Unix socket "
            "behind the reverse proxy"
        )
    if str(
        environ.get(
            "PRICE_MIXER_FORWARDED_ALLOW_IPS", "127.0.0.1"
        )
        or ""
    ).strip() == "*":
        errors.append(
            "PRICE_MIXER_FORWARDED_ALLOW_IPS must not trust every address"
        )

    backup_dir_text = str(
        environ.get(
            "PRICE_MIXER_BACKUP_DIR",
            "/srv/price-mixer-backups",
        )
        or ""
    ).strip()
    backup_dir = PurePosixPath(backup_dir_text)
    project_dir = PurePosixPath("/opt/price-mixer/current")
    if not backup_dir_text.startswith("/"):
        errors.append("PRICE_MIXER_BACKUP_DIR must be an absolute path")
    elif backup_dir == project_dir or project_dir in backup_dir.parents:
        errors.append(
            "PRICE_MIXER_BACKUP_DIR must be outside the application directory"
        )

    runtime_directories = {}
    for key, default in (
        ("PRICE_MIXER_STATE_DIR", "/var/lib/price-mixer/state"),
        ("PRICE_MIXER_DATA_DIR", "/var/lib/price-mixer/data"),
        ("PRICE_MIXER_CACHE_DIR", "/var/cache/price-mixer"),
        ("PRICE_MIXER_UPLOAD_DIR", "/var/lib/price-mixer/uploads"),
        ("PRICE_MIXER_LOG_DIR", "/var/log/price-mixer"),
    ):
        value = str(environ.get(key, default) or "").strip()
        path = PurePosixPath(value)
        if not value.startswith("/"):
            errors.append(f"{key} must be an absolute path")
            continue
        if path == project_dir or project_dir in path.parents:
            errors.append(f"{key} must be outside the application directory")
            continue
        runtime_directories[key] = path
    if len(set(runtime_directories.values())) != len(runtime_directories):
        errors.append("PRICE_MIXER runtime directories must be distinct")

    if str(
        environ.get("PRICE_MIXER_JOB_MODE", "external") or ""
    ).strip().casefold() != "external":
        errors.append("PRICE_MIXER_JOB_MODE must be external in production")
    job_db_text = str(
        environ.get(
            "PRICE_MIXER_JOB_DB",
            "/var/lib/price-mixer/data/jobs.db",
        )
        or ""
    ).strip()
    job_db = PurePosixPath(job_db_text)
    if not job_db_text.startswith("/"):
        errors.append("PRICE_MIXER_JOB_DB must be an absolute path")
    data_dir = runtime_directories.get("PRICE_MIXER_DATA_DIR")
    if data_dir is not None and not (
        job_db.parent == data_dir or data_dir in job_db.parents
    ):
        errors.append("PRICE_MIXER_JOB_DB must be inside PRICE_MIXER_DATA_DIR")

    if (
        str(environ.get("ADMIN_PASSWORD", "") or "").strip()
        and str(environ.get("ADMIN_PASSWORD", "") or "").strip()
        == str(environ.get("FLASK_SECRET_KEY", "") or "").strip()
    ):
        errors.append(
            "ADMIN_PASSWORD and FLASK_SECRET_KEY must be different"
        )
    return errors


def require_valid_production_environment(environ):
    errors = validate_production_environment(environ)
    if errors:
        raise RuntimeError(
            "Invalid production configuration: " + "; ".join(errors)
        )
