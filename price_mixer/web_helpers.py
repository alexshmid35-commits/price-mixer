"""Small web-layer helpers kept outside the Flask monolith."""

from __future__ import annotations

import hmac
import re
from pathlib import Path
from typing import MutableMapping


SESSION_ID_RE = re.compile(r"[0-9a-fA-F-]{8,36}")


def resolve_session_dir(upload_dir: Path, session_id: object) -> Path | None:
    """Resolve a session id to a directory under ``upload_dir``."""
    session_id = str(session_id or "").strip()
    if not session_id or not SESSION_ID_RE.fullmatch(session_id):
        return None
    upload_root = Path(upload_dir).resolve()
    candidate = (upload_root / session_id).resolve()
    try:
        candidate.relative_to(upload_root)
    except ValueError:
        return None
    return candidate


def validate_session_dir_path(upload_dir: Path, raw_path: object) -> Path | None:
    """Accept only legacy session paths that already live under ``upload_dir``."""
    if not raw_path:
        return None
    upload_root = Path(upload_dir).resolve()
    try:
        candidate = Path(str(raw_path)).resolve()
        candidate.relative_to(upload_root)
    except (OSError, ValueError):
        return None
    return candidate


def active_session_dir(upload_dir: Path, session_data: MutableMapping[str, object]) -> Path | None:
    """Return the active session directory and scrub legacy path fields.

    ``session_data`` is intentionally a mapping so this can be tested without a
    Flask request context. Flask's signed session object satisfies this shape.
    """
    candidate = resolve_session_dir(upload_dir, session_data.get("session_id"))
    if candidate and candidate.exists():
        session_data.pop("session_dir", None)
        session_data.pop("output_path", None)
        return candidate

    legacy = validate_session_dir_path(upload_dir, session_data.get("session_dir"))
    if legacy and legacy.exists():
        session_data["session_id"] = legacy.name
        session_data.pop("session_dir", None)
        session_data.pop("output_path", None)
        return legacy

    session_data.pop("session_dir", None)
    session_data.pop("output_path", None)
    return None


def basic_auth_matches(auth, expected_username: str, expected_password: str) -> bool:
    """Constant-time-ish comparison for Flask/Werkzeug Basic Auth objects."""
    if not auth:
        return False
    return hmac.compare_digest(str(auth.username or ""), str(expected_username)) and hmac.compare_digest(
        str(auth.password or ""), str(expected_password)
    )
