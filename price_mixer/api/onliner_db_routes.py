"""Onliner local database API routes."""

from __future__ import annotations

from typing import Callable

from flask import Blueprint, jsonify, request
from price_mixer.api.response import as_response as _as_response



def create_onliner_db_bp(
    *,
    get_stats: Callable[[], dict],
    search: Callable[[str], dict | tuple[dict, int]],
    rebuild: Callable[[str | None], dict | tuple[dict, int]],
    import_gsheet: Callable[[dict], dict | tuple[dict, int]],
    import_csv: Callable[[object], dict | tuple[dict, int]],
    get_import_status: Callable[[], dict],
    get_active_session_dir: Callable[[], str | None],
) -> Blueprint:
    bp = Blueprint("onliner_db_api", __name__)

    @bp.route("/api/onliner-db-stats")
    def api_onliner_db_stats():
        resp = jsonify(get_stats())
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @bp.route("/api/onliner-db-search")
    def api_onliner_db_search():
        query = str(request.args.get("q", "") or "").strip()
        if not query:
            return jsonify({"items": []})
        return _as_response(search(query))

    @bp.route("/api/onliner-db-rebuild", methods=["POST"])
    def api_onliner_db_rebuild():
        return _as_response(rebuild(get_active_session_dir()))

    @bp.route("/api/onliner-db-import-gsheet", methods=["POST"])
    def api_onliner_db_import_gsheet():
        return _as_response(import_gsheet(request.get_json(silent=True) or {}))

    @bp.route("/api/onliner-db-import-csv", methods=["POST"])
    def api_onliner_db_import_csv():
        return _as_response(import_csv(request.files.get("file")))

    @bp.route("/api/onliner-db-import-status")
    def api_onliner_db_import_status():
        resp = jsonify(get_import_status())
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp

    return bp
