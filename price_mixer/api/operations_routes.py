"""Operational status, queue control, and parser reprocessing routes."""

from __future__ import annotations

from collections.abc import Callable

from flask import Blueprint

from price_mixer.api.response import as_response as _as_response


def create_operations_bp(
    *,
    background_xlsx_status: Callable,
    worker_status: Callable,
    sorting_reparse_run: Callable,
    sorting_reparse_run_all: Callable,
    sorting_reparse_status: Callable,
    cancel_job: Callable[[str], dict | tuple[dict, int]],
    resume_job: Callable[[str], dict | tuple[dict, int]],
) -> Blueprint:
    bp = Blueprint("operations_api", __name__)

    @bp.get("/api/background-xlsx-status")
    def api_background_xlsx_status():
        return _as_response(background_xlsx_status())

    @bp.get("/api/worker-status")
    def api_worker_status():
        return _as_response(worker_status())

    @bp.post("/api/sorting-reparse/run")
    def api_sorting_reparse_run():
        return _as_response(sorting_reparse_run())

    @bp.post("/api/sorting-reparse/run-all")
    def api_sorting_reparse_run_all():
        return _as_response(sorting_reparse_run_all())

    @bp.get("/api/sorting-reparse/status")
    def api_sorting_reparse_status():
        return _as_response(sorting_reparse_status())

    @bp.post("/api/jobs/<job_id>/cancel")
    def api_cancel_job(job_id):
        return _as_response(cancel_job(job_id))

    @bp.post("/api/jobs/<job_id>/resume")
    def api_resume_job(job_id):
        return _as_response(resume_job(job_id))

    return bp
