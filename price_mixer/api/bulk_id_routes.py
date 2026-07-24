"""Bulk Onliner ID cleanup API routes."""

from __future__ import annotations

from typing import Callable

from flask import Blueprint, request
from price_mixer.api.response import as_response as _as_response


def create_bulk_id_bp(
    *,
    get_active_session_dir: Callable[[], str | None],
    clear_invalid: Callable[[str | None, dict], dict | tuple[dict, int]],
    clear_all_nonpc: Callable[[str | None], dict | tuple[dict, int]],
    clear_ntech_duplicates: Callable[[str | None], dict | tuple[dict, int]],
) -> Blueprint:
    bp = Blueprint("bulk_id_api", __name__)

    @bp.route("/api/clear-invalid-onliner-ids", methods=["POST"])
    def api_clear_invalid_onliner_ids():
        return _as_response(clear_invalid(
            get_active_session_dir(),
            request.get_json(silent=True) or {},
        ))

    @bp.route("/api/clear-all-nonpc-onliner-ids", methods=["POST"])
    def api_clear_all_nonpc_onliner_ids():
        return _as_response(clear_all_nonpc(get_active_session_dir()))

    @bp.route("/api/clear-ntech-duplicate-onliner-ids", methods=["POST"])
    def api_clear_ntech_duplicate_onliner_ids():
        return _as_response(clear_ntech_duplicates(get_active_session_dir()))

    return bp
