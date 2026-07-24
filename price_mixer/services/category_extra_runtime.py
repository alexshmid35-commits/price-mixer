"""Runtime facade for category extra endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class CategoryExtraRuntime:
    get_active_session_dir: Callable[[], str | None]
    resolve_session_dir: Callable[[str], Path | None]
    has_consolidated_session_file: Callable[[str | Path], bool]
    lock: object
    load_category_markups: Callable[[], dict]
    load_category_overrides: Callable[[], dict]
    save_category_overrides: Callable[[dict], None]
    load_manual_category_overrides: Callable[[], dict]
    save_manual_category_overrides: Callable[[dict], None]
    read_consolidated_json_fast_df: Callable
    ensure_category_column: Callable
    apply_visibility_filter: Callable
    apply_saved_markups_to_df: Callable
    write_consolidated_df: Callable
    write_consolidated_json: Callable
    apply_category_override_to_df: Callable
    autosort_preview_payload: Callable
    autosort_apply_items: Callable
    canonical_ui_category_name: Callable
    build_item_category_keys: Callable
    build_item_category_key: Callable
    row_category: Callable
    name_tokens: Callable
    normalize_onliner_id: Callable
    category_sort_key: Callable
    predict_openai_category: Callable
    openai_api_key: str
    autosort_max_items: int
    autosort_max_workers: int

    def markups(self):
        return {"markups": self.load_category_markups()}

    def override_bulk(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        session_dir = self.get_active_session_dir()
        requested_sid = str(payload.get("sid", "") or "").strip()
        if requested_sid:
            requested_dir = self.resolve_session_dir(requested_sid)
            if requested_dir is None or not self.has_consolidated_session_file(requested_dir):
                return {"status": "error", "message": "Сессия прайса не найдена"}, 404
            session_dir = str(requested_dir)

        item_keys = payload.get("item_keys", [])
        target_category = self.canonical_ui_category_name(payload.get("target_category", ""))
        if not isinstance(item_keys, list) or not item_keys:
            return {"status": "error", "message": "Не выбраны товары"}
        if not target_category:
            return {"status": "error", "message": "Не выбрана целевая категория"}

        keys = [str(k).strip() for k in item_keys if str(k).strip()]
        if not keys:
            return {"status": "error", "message": "Не выбраны товары"}

        with self.lock:
            explicit_overrides = self.load_manual_category_overrides()
            overrides = self.load_category_overrides()
            df = None
            if session_dir and self.has_consolidated_session_file(session_dir):
                df = self.read_consolidated_json_fast_df(session_dir)
                df = self.ensure_category_column(df, overrides)
            result, df, overrides, updated_rows = self.apply_category_override_to_df(
                df,
                {"item_keys": keys, "target_category": target_category},
                overrides=overrides,
                build_item_category_keys=self.build_item_category_keys,
                explicit_overrides=explicit_overrides,
            )
            if result.get("status") != "ok":
                return result
            if updated_rows and session_dir:
                df = self.apply_saved_markups_to_df(df)
                self.write_consolidated_df(session_dir, df)
                self.write_consolidated_json(df, Path(session_dir) / "consolidated.json")
            self.save_category_overrides(overrides)
            self.save_manual_category_overrides(explicit_overrides)

        return {"status": "ok", "updated": len(keys), "updated_rows": updated_rows}

    def autosort_preview(self, payload):
        session_dir = self.get_active_session_dir()
        if not session_dir or not self.has_consolidated_session_file(session_dir):
            return {"items": [], "checked": 0, "skipped": 0}

        df = self.read_consolidated_json_fast_df(session_dir)
        if "Название" not in df.columns:
            return {"items": [], "checked": 0, "skipped": 0}
        df = self.ensure_category_column(df)
        df = self.apply_visibility_filter(df, session_dir)
        return self.autosort_preview_payload(
            df,
            payload if isinstance(payload, dict) else {},
            overrides=self.load_category_overrides(),
            openai_api_key=self.openai_api_key,
            max_items=self.autosort_max_items,
            max_workers=self.autosort_max_workers,
            predict_category=self.predict_openai_category,
            name_tokens=self.name_tokens,
            row_category=self.row_category,
            build_item_category_key=self.build_item_category_key,
            build_item_category_keys=self.build_item_category_keys,
            normalize_onliner_id=self.normalize_onliner_id,
            category_sort_key=self.category_sort_key,
        )

    def autosort_apply(self, payload):
        session_dir = self.get_active_session_dir()
        if not session_dir:
            return {"status": "error", "message": "No session"}
        if not self.has_consolidated_session_file(session_dir):
            return {"status": "error", "message": "No data"}

        df = self.read_consolidated_json_fast_df(session_dir)
        payload = payload if isinstance(payload, dict) else {}
        overrides = self.load_category_overrides()
        df = self.ensure_category_column(df, overrides)
        result, df, overrides = self.autosort_apply_items(
            df,
            payload.get("items", []),
            overrides=overrides,
            build_item_category_keys=self.build_item_category_keys,
            row_category=self.row_category,
        )
        if result.get("status") != "ok":
            return result

        self.write_consolidated_df(session_dir, df)
        self.write_consolidated_json(df, Path(session_dir) / "consolidated.json")
        self.save_category_overrides(overrides)
        return result

    def reapply_saved_markups(self):
        session_dir = self.get_active_session_dir()
        if not session_dir:
            return {"status": "error", "message": "Нет активной сессии"}, 400
        if not self.has_consolidated_session_file(session_dir):
            return {"status": "error", "message": "Сводный прайс не найден"}, 400

        df = self.read_consolidated_json_fast_df(session_dir)
        if df.empty:
            return {"status": "ok", "updated_rows": 0}

        if "РРЦ" not in df.columns:
            df["РРЦ"] = ""

        import numpy as np
        import pandas as pd

        before_rrc = pd.to_numeric(df["РРЦ"], errors="coerce")
        df2 = self.apply_saved_markups_to_df(df.copy())
        after_rrc = pd.to_numeric(df2.get("РРЦ", pd.Series(dtype=float)), errors="coerce")

        changed = 0
        for i in df2.index:
            before = before_rrc.loc[i] if i in before_rrc.index else np.nan
            after = after_rrc.loc[i] if i in after_rrc.index else np.nan
            if (pd.isna(before) and pd.notna(after)) or (
                pd.notna(before) and pd.notna(after) and float(before) != float(after)
            ):
                changed += 1

        self.write_consolidated_df(session_dir, df2)
        self.write_consolidated_json(df2, Path(session_dir) / "consolidated.json")
        return {"status": "ok", "updated_rows": int(changed)}
