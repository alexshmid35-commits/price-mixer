"""Safe filesystem and SQLite checks for production startup."""

from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path


RUNTIME_DIRECTORY_DEFAULTS = (
    ("PRICE_MIXER_STATE_DIR", "/var/lib/price-mixer/state"),
    ("PRICE_MIXER_DATA_DIR", "/var/lib/price-mixer/data"),
    ("PRICE_MIXER_CACHE_DIR", "/var/cache/price-mixer"),
    ("PRICE_MIXER_UPLOAD_DIR", "/var/lib/price-mixer/uploads"),
    ("PRICE_MIXER_LOG_DIR", "/var/log/price-mixer"),
)


def check_runtime_readiness(environ=None):
    """Return sanitized errors; never include path or secret values."""
    env = os.environ if environ is None else environ
    errors = []
    directories = {}
    for key, default in RUNTIME_DIRECTORY_DEFAULTS:
        directory = Path(str(env.get(key, default) or default))
        directories[key] = directory
        if not directory.is_dir():
            errors.append(f"{key} directory does not exist")
            continue
        probe = directory / f".price-mixer-preflight-{uuid.uuid4().hex}"
        try:
            with probe.open("x", encoding="utf-8") as handle:
                handle.write("ok")
        except OSError:
            errors.append(f"{key} directory is not writable")
        finally:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                errors.append(f"{key} write probe could not be removed")

    data_dir = directories["PRICE_MIXER_DATA_DIR"]
    job_db = Path(
        str(
            env.get(
                "PRICE_MIXER_JOB_DB",
                data_dir / "jobs.db",
            )
            or data_dir / "jobs.db"
        )
    )
    for label, database in (
        ("onliner_products.db", data_dir / "onliner_products.db"),
        ("jobs.db", job_db),
    ):
        if database.exists():
            error = _sqlite_quick_check(database)
            if error:
                errors.append(f"{label} failed SQLite quick_check")
    return errors


def _sqlite_quick_check(path):
    try:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
        if not row or str(row[0]).casefold() != "ok":
            return "quick_check failed"
    except (OSError, sqlite3.Error):
        return "quick_check failed"
    return ""
