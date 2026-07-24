"""Manual Onliner ID API routes."""

from __future__ import annotations

from typing import Callable

from flask import Blueprint, request
from price_mixer.api.response import as_response as _as_response


def create_manual_id_bp(
    *,
    get_active_session_dir: Callable[[], str | None],
    confirm_batch: Callable[[str | None, dict], dict | tuple[dict, int]],
    clear: Callable[[str | None, dict], dict | tuple[dict, int]],
    rollback_last: Callable[[str | None], dict | tuple[dict, int]],
) -> Blueprint:
    bp = Blueprint("manual_id_api", __name__)

    @bp.route("/api/manual-id-confirm-batch", methods=["POST"])
    def api_manual_id_confirm_batch():
        return _as_response(confirm_batch(
            get_active_session_dir(),
            request.get_json(silent=True) or {},
        ))

    @bp.route("/api/manual-id-clear", methods=["POST"])
    def api_manual_id_clear():
        return _as_response(clear(
            get_active_session_dir(),
            request.get_json(silent=True) or {},
        ))

    @bp.route("/api/manual-id-rollback-last", methods=["POST"])
    def api_manual_id_rollback_last():
        return _as_response(rollback_last(get_active_session_dir()))

    return bp
