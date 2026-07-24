"""Onliner ID reporting and candidate search API routes."""

from __future__ import annotations

from typing import Callable

from flask import Blueprint, request
from price_mixer.api.response import as_response as _as_response


def create_id_reporting_bp(
    *,
    replace_candidates: Callable[[dict], dict | tuple[dict, int]],
    check_duplicate_ids: Callable[[], dict | tuple[dict, int]],
    get_quality_report: Callable[[], dict | tuple[dict, int]],
) -> Blueprint:
    bp = Blueprint("id_reporting_api", __name__)

    @bp.route("/api/id-replace-candidates", methods=["POST"])
    def api_id_replace_candidates():
        return _as_response(replace_candidates(request.get_json(silent=True) or {}))

    @bp.route("/api/check-duplicate-onliner-ids", methods=["POST"])
    def api_check_duplicate_onliner_ids():
        return _as_response(check_duplicate_ids())

    @bp.route("/api/id-quality-report")
    def api_id_quality_report():
        return _as_response(get_quality_report())

    return bp
