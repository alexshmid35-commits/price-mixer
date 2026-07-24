"""Runtime facade for N-Tech review queue scans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from price_mixer.services.ntech_review_queue import (
    build_review_queue_finish_payload,
    run_review_queue_scan,
)


@dataclass(frozen=True)
class NTechReviewRuntime:
    get_active_session_dir: Callable[[], str | None]
    has_consolidated_session_file: Callable
    consolidated_json_df: Callable
    read_consolidated_json_fast_df: Callable
    ensure_category_column: Callable
    precomputed_row_category: Callable
    row_category: Callable
    get_handler: Callable
    load_review_queue: Callable[[], dict]
    save_review_queue: Callable[[dict], None]
    normalize_catalog_category_name: Callable
    normalize_onliner_id: Callable
    status: dict
    status_lock: object
    clock: Callable[[], float]

    def start(
        self,
        *,
        report_mode,
        report_title,
        success_message,
        empty_message,
        report_subtitle,
        empty_report_subtitle,
        handler_mode=None,
        is_target_row=None,
        build_row_result=None,
        include_no_model=True,
        supplier_names=None,
    ):
        session_dir = self.get_active_session_dir()
        if not session_dir:
            return {"status": "error", "message": "Нет активной сессии"}, 400
        if not self.has_consolidated_session_file(session_dir):
            return {"status": "error", "message": "Нет данных"}, 400

        df = self.consolidated_json_df(session_dir, apply_visibility=True)
        row_category_func = self.precomputed_row_category
        if df is None:
            df = self.read_consolidated_json_fast_df(session_dir)
            df = self.ensure_category_column(df)
            row_category_func = self.row_category
        if df.empty:
            return {"status": "error", "message": "Прайс пуст"}, 400

        if handler_mode:
            handler = self.get_handler(handler_mode)
            is_target_row = handler.is_target
            build_row_result = handler.build_row_result

        queue = self.load_review_queue()
        now_ts = int(self.clock())
        scan = run_review_queue_scan(
            df,
            queue,
            now_ts=now_ts,
            is_target_row=is_target_row,
            build_row_result=build_row_result,
            row_category=row_category_func,
            normalize_catalog_category_name=self.normalize_catalog_category_name,
            normalize_onliner_id=self.normalize_onliner_id,
            ntech_supplier_names=supplier_names,
        )
        self.save_review_queue(queue)

        finish_kwargs = {
            "report_mode": report_mode,
            "report_title": report_title,
            "report_items": scan["report_items"],
            "scanned": scan["scanned"],
            "queued": scan["queued"],
            "no_candidates": scan["no_candidates"],
            "skipped_with_id": scan["skipped_with_id"],
            "skipped_non_ntech": scan["skipped_non_ntech"],
            "success_message": success_message(scan),
            "empty_message": empty_message,
            "report_subtitle": report_subtitle(scan),
            "empty_report_subtitle": empty_report_subtitle,
            "now_ts": now_ts,
        }
        if include_no_model:
            finish_kwargs["no_model"] = scan["no_model"]

        payload, status_update = build_review_queue_finish_payload(**finish_kwargs)
        with self.status_lock:
            self.status.update(status_update)
        return payload
