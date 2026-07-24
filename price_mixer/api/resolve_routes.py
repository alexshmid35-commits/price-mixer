"""Onliner URL resolve API routes."""

from collections.abc import Callable

from flask import Blueprint
from price_mixer.api.response import as_response as _as_response


def create_resolve_bp(
    *,
    start: Callable[[], object],
    status: Callable[[], object],
) -> Blueprint:
    bp = Blueprint("resolve_api", __name__)
    bp.add_url_rule("/api/resolve-start", "api_resolve_start", lambda: _as_response(start()), methods=["POST"])
    bp.add_url_rule("/api/resolve-status", "api_resolve_status", lambda: _as_response(status()))
    return bp
