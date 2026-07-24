"""Runtime facade for core category management endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class CategoryManagementRuntime:
    get_active_session_dir: Callable[[], str | None]
    canonical_supplier_name: Callable
    load_visibility_map: Callable[[str], dict]
    save_visibility_map: Callable[[str, dict], None]
    update_category_visibility: Callable
    category_sort_key: Callable
    visibility_lock: object
    has_consolidated_session_file: Callable[[str], bool]
    consolidated_json_df: Callable
    read_consolidated_json_fast_df: Callable
    read_consolidated_df: Callable
    ensure_category_column: Callable
    apply_visibility_filter: Callable
    parse_markup_request: Callable
    apply_markup_to_df: Callable
    markup_preview_payload: Callable
    row_category: Callable
    normalize_onliner_id: Callable
    get_onliner_market_stats_bulk: Callable
    write_consolidated_json: Callable
    write_consolidated_df_background: Callable
    load_category_markups: Callable[[], dict]
    save_category_markups: Callable[[dict], None]
    update_category_markups: Callable
    load_category_overrides: Callable[[], dict]
    save_category_overrides: Callable[[dict], None]
    load_manual_category_overrides: Callable[[], dict]
    save_manual_category_overrides: Callable[[dict], None]
    category_override_items_payload: Callable
    apply_category_override_to_df: Callable
    canonical_ui_category_name: Callable
    build_item_category_key: Callable
    build_item_category_keys: Callable
    infer_category: Callable
    write_consolidated_df: Callable
    override_lock: object
    category_preview_items_payload: Callable
    load_market_cache: Callable[[], dict]
    get_market_stats_from_cache_only: Callable

    def visibility(self, payload):
        session_dir = self.get_active_session_dir()
        if not session_dir:
            return {
                "status": "error",
                "message": "Нет активной сессии",
            }, 400

        payload = dict(payload) if isinstance(payload, dict) else {}
        payload["supplier"] = self.canonical_supplier_name(
            payload.get("supplier")
        )
        with self.visibility_lock:
            result, visibility_map, status_code = (
                self.update_category_visibility(
                    payload,
                    self.load_visibility_map(session_dir),
                    category_sort_key=self.category_sort_key,
                )
            )
            if status_code == 200:
                self.save_visibility_map(session_dir, visibility_map)
        return result, status_code

    def apply_markup(self, payload):
        session_dir = self.get_active_session_dir()
        if not session_dir:
            return {"status": "error", "message": "No session"}
        if not self.has_consolidated_session_file(session_dir):
            return {"status": "error", "message": "No data"}

        markup_cfg, error = self.parse_markup_request(
            payload if isinstance(payload, dict) else {}
        )
        if error:
            return {"status": "error", "message": error}

        frame = self.read_consolidated_json_fast_df(session_dir)
        frame = self.ensure_category_column(frame)
        frame, result = self.apply_markup_to_df(
            frame,
            markup_cfg,
            row_category=self.row_category,
            normalize_onliner_id=self.normalize_onliner_id,
            get_onliner_market_stats_bulk=self.get_onliner_market_stats_bulk,
        )
        if result.get("status") != "ok":
            return result

        self.write_consolidated_json(
            frame, Path(session_dir) / "consolidated.json"
        )
        markups = self.update_category_markups(
            self.load_category_markups(), markup_cfg
        )
        self.save_category_markups(markups)
        self.write_consolidated_df_background(
            session_dir, frame, label="apply-markup"
        )
        return result

    def markup_preview(self, payload):
        session_dir = self.get_active_session_dir()
        if (
            not session_dir
            or not self.has_consolidated_session_file(session_dir)
        ):
            return {"items": []}

        frame = self.consolidated_json_df(
            session_dir, apply_visibility=True
        )
        if frame is None:
            frame = self.read_consolidated_df(session_dir)
            frame = self.ensure_category_column(frame)
            frame = self.apply_visibility_filter(frame, session_dir)
        return self.markup_preview_payload(
            frame,
            payload if isinstance(payload, dict) else {},
            row_category=self.row_category,
        )

    def category_override_items(self, *, query="", limit=40):
        session_dir = self.get_active_session_dir()
        if (
            not session_dir
            or not self.has_consolidated_session_file(session_dir)
        ):
            return {"items": []}

        frame = self.consolidated_json_df(
            session_dir, apply_visibility=False
        )
        if frame is None:
            frame = self.read_consolidated_df(session_dir)
            frame = self.ensure_category_column(frame)
        return self.category_override_items_payload(
            frame,
            query=query,
            limit=limit,
            overrides=self.load_category_overrides(),
            build_item_category_key=self.build_item_category_key,
            infer_category=self.infer_category,
            row_category=self.row_category,
        )

    def category_override_set(self, payload):
        session_dir = self.get_active_session_dir()
        payload = dict(payload) if isinstance(payload, dict) else {}
        payload["target_category"] = self.canonical_ui_category_name(
            payload.get("target_category", "")
        )

        with self.override_lock:
            explicit_overrides = self.load_manual_category_overrides()
            overrides = self.load_category_overrides()
            frame = None
            if (
                session_dir
                and self.has_consolidated_session_file(session_dir)
            ):
                frame = self.read_consolidated_json_fast_df(session_dir)
                frame = self.ensure_category_column(frame, overrides)
            result, frame, overrides, changed = (
                self.apply_category_override_to_df(
                    frame,
                    payload,
                    overrides=overrides,
                    build_item_category_keys=self.build_item_category_keys,
                    explicit_overrides=explicit_overrides,
                )
            )
            if result.get("status") != "ok":
                return result
            if changed and session_dir:
                self.write_consolidated_df(session_dir, frame)
                self.write_consolidated_json(
                    frame, Path(session_dir) / "consolidated.json"
                )
            self.save_category_overrides(overrides)
            self.save_manual_category_overrides(explicit_overrides)
        return result

    def category_preview_items(self, payload):
        session_dir = self.get_active_session_dir()
        if (
            not session_dir
            or not self.has_consolidated_session_file(session_dir)
        ):
            return {"items": []}

        frame = self.consolidated_json_df(
            session_dir, apply_visibility=True
        )
        if frame is None:
            frame = self.read_consolidated_df(session_dir)
            frame = self.ensure_category_column(frame)
            frame = self.apply_visibility_filter(frame, session_dir)
        return self.category_preview_items_payload(
            frame,
            payload if isinstance(payload, dict) else {},
            overrides=self.load_category_overrides(),
            row_category=self.row_category,
            build_item_category_key=self.build_item_category_key,
            normalize_onliner_id=self.normalize_onliner_id,
            load_market_cache=self.load_market_cache,
            get_market_stats_from_cache_only=(
                self.get_market_stats_from_cache_only
            ),
        )
