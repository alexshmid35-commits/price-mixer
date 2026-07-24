"""Routes for the experimental all-products no-ID candidate review."""

from __future__ import annotations

from flask import Blueprint, request

from price_mixer.api.response import as_response


def create_experimental_noid_bp(*, get_active_session_dir, get_runtime):
    bp = Blueprint("experimental_noid_api", __name__)

    @bp.post("/api/experimental-noid/start")
    def start():
        return as_response(get_runtime().start(get_active_session_dir()))

    @bp.get("/api/experimental-noid/status")
    def status():
        return as_response(get_runtime().status(
            get_active_session_dir(),
            request.args.get("job_id", ""),
        ))

    @bp.get("/api/experimental-noid/items")
    def items():
        return as_response(get_runtime().items(get_active_session_dir(), request.args))

    @bp.get("/api/experimental-noid/quality")
    def quality():
        return as_response(get_runtime().quality(
            get_active_session_dir(),
            request.args.get("job_id", ""),
        ))

    @bp.post("/api/experimental-noid/decision")
    def decision():
        return as_response(get_runtime().decide(
            get_active_session_dir(),
            request.get_json(silent=True) or {},
        ))

    return bp
