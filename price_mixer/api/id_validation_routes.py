"""Onliner ID verification and validation API routes."""

from __future__ import annotations

from typing import Callable

from flask import Blueprint
from price_mixer.api.response import as_response as _as_response


def create_id_validation_bp(
    *,
    verify_all_start: Callable[[], dict | tuple[dict, int]],
    get_verify_all_status: Callable[[], dict],
    validate_clean_start: Callable[[], dict | tuple[dict, int]],
    validate_clean_db_start: Callable[[], dict | tuple[dict, int]],
    validate_clean_cancel: Callable[[], dict | tuple[dict, int]],
    get_validate_clean_status: Callable[[], dict],
) -> Blueprint:
    bp = Blueprint("id_validation_api", __name__)

    @bp.route("/api/verify-all-ids-start", methods=["POST"])
    def api_verify_all_ids_start():
        return _as_response(verify_all_start())

    @bp.route("/api/verify-all-ids-status")
    def api_verify_all_ids_status():
        return _as_response(get_verify_all_status())

    @bp.route("/api/validate-clean-ids-start", methods=["POST"])
    def api_validate_clean_ids_start():
        return _as_response(validate_clean_start())

    @bp.route("/api/validate-clean-ids-db-start", methods=["POST"])
    def api_validate_clean_ids_db_start():
        return _as_response(validate_clean_db_start())

    @bp.route("/api/validate-clean-ids-cancel", methods=["POST"])
    def api_validate_clean_ids_cancel():
        return _as_response(validate_clean_cancel())

    @bp.route("/api/validate-clean-ids-status")
    def api_validate_clean_ids_status():
        return _as_response(get_validate_clean_status())

    return bp
