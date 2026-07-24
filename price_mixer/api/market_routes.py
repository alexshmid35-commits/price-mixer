"""Market refresh API routes."""

from __future__ import annotations

from typing import Callable

from flask import Blueprint, jsonify, request


def format_market_refresh_status(status: dict) -> dict:
    """Normalize the market-refresh status payload returned to the UI."""
    st = dict(status or {})
    cats = st.get("categories", {}) or {}
    cats_pct = {
        k: {
            "done": int(v.get("done", 0)),
            "total": int(v.get("total", 0)),
            "percent": int(v.get("percent", 0)),
            "errors": int(v.get("errors", 0) or 0),
            "recent_errors": list(v.get("recent_errors", []) or []),
        }
        for k, v in cats.items()
        if isinstance(v, dict)
    }
    total = int(st.get("total", 0) or 0)
    done = int(st.get("done", 0) or 0)
    overall = int(round((done / max(total, 1)) * 100)) if total else 0
    return {
        "running": bool(st.get("running")),
        "total": total,
        "done": done,
        "success": int(st.get("success", 0) or 0),
        "errors": int(st.get("errors", 0) or 0),
        "overall_percent": overall,
        "categories": cats_pct,
        "recent_errors": list(st.get("recent_errors", []) or []),
        "phase": str(st.get("phase", "") or ""),
        "message": str(st.get("message", "") or ""),
        "started_at": int(st.get("started_at", 0) or 0),
        "finished_at": int(st.get("finished_at", 0) or 0),
    }


def create_market_bp(
    *,
    get_active_session_dir: Callable[[], str | None],
    start_market_refresh: Callable[[str, list], dict],
    get_market_refresh_status: Callable[[], dict],
) -> Blueprint:
    bp = Blueprint("market_api", __name__)

    @bp.route("/api/market-refresh-start", methods=["POST"])
    def api_market_refresh_start():
        session_dir = get_active_session_dir()
        if not session_dir:
            return jsonify({"status": "error", "message": "No session"})
        payload = request.get_json(silent=True) or {}
        categories = payload.get("categories", [])
        if not isinstance(categories, list):
            categories = []
        return jsonify(start_market_refresh(str(session_dir), categories))

    @bp.route("/api/market-refresh-status")
    def api_market_refresh_status():
        return jsonify(format_market_refresh_status(get_market_refresh_status()))

    return bp
