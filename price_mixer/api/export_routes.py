"""Export and download API routes."""

from collections.abc import Callable

from flask import Blueprint
from price_mixer.api.response import as_response as _as_response


def create_export_bp(
    *,
    download: Callable[[], object],
    export_google_sheets: Callable[[], object],
    download_id_quality_report: Callable[[], object],
    preexport_quality_check: Callable[[], object],
    download_id_compare_report: Callable[[], object] | None = None,
) -> Blueprint:
    bp = Blueprint("export_api", __name__)
    bp.add_url_rule("/download", "download", lambda: _as_response(download()))
    bp.add_url_rule("/api/export-google-sheets", "api_export_google_sheets", lambda: _as_response(export_google_sheets()), methods=["POST"])
    bp.add_url_rule("/download/id-quality-report", "download_id_quality_report", lambda: _as_response(download_id_quality_report()))
    if download_id_compare_report is not None:
        bp.add_url_rule("/download/id-compare-report", "download_id_compare_report", lambda: _as_response(download_id_compare_report()))
    bp.add_url_rule("/api/preexport-quality-check", "api_preexport_quality_check", lambda: _as_response(preexport_quality_check()))
    return bp
