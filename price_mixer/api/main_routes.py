"""Main page, upload, and consolidated data routes."""

from collections.abc import Callable

from flask import Blueprint
from price_mixer.api.response import as_response as _as_response


def create_main_bp(
    *,
    index: Callable[[], object],
    result_page: Callable[[], object],
    upload: Callable[[], object],
    consolidated: Callable[[], object],
    consolidated_page: Callable[[], object],
    stats: Callable[[], object],
    export_row_indexes: Callable[[], object],
) -> Blueprint:
    bp = Blueprint("main_api", __name__)
    bp.add_url_rule("/", "index", lambda: _as_response(index()))
    bp.add_url_rule("/result", "result_page", lambda: _as_response(result_page()))
    bp.add_url_rule("/upload", "upload", lambda: _as_response(upload()), methods=["POST"])
    bp.add_url_rule("/api/consolidated", "api_consolidated", lambda: _as_response(consolidated()))
    bp.add_url_rule("/api/consolidated-page", "api_consolidated_page", lambda: _as_response(consolidated_page()))
    bp.add_url_rule("/api/stats", "api_stats", lambda: _as_response(stats()))
    bp.add_url_rule("/api/export-row-indexes", "api_export_row_indexes", lambda: _as_response(export_row_indexes()))
    return bp
