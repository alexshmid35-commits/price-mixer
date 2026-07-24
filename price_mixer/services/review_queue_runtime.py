"""Runtime facade for listing and resolving the manual review queue."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from price_mixer.services.review_queue import (
    build_list_items,
    dataframe_id_conflict_for_supplier,
    manual_binding_id_conflict,
    match_name_key,
    row_matches_supplier_names,
    unique_supplier_names,
)


@dataclass(frozen=True)
class ReviewQueueRuntime:
    get_active_session_dir: Callable[[], str | None]
    load_review_queue: Callable[[], dict]
    save_review_queue: Callable[[dict], None]
    read_consolidated_json_fast_df: Callable
    write_consolidated_json: Callable
    write_consolidated_df_background: Callable
    load_manual_id_bindings: Callable[[], dict]
    save_manual_id_bindings: Callable[[dict], None]
    append_id_change_journal: Callable[[dict], None]
    normalize_name_key: Callable
    normalize_onliner_id: Callable
    manual_binding_scoped_key: Callable
    clock: Callable[[], float]

    def list(self):
        queue = self.load_review_queue()
        if not queue:
            return {"items": []}

        frame = None
        session_dir = self.get_active_session_dir()
        if session_dir:
            try:
                frame = self.read_consolidated_json_fast_df(session_dir)
            except Exception:
                frame = None

        items, stale_keys = build_list_items(
            queue,
            frame,
            normalize_name_key=self.normalize_name_key,
            normalize_onliner_id=self.normalize_onliner_id,
        )
        if stale_keys:
            for queue_key in stale_keys:
                queue.pop(queue_key, None)
            self.save_review_queue(queue)
        return {"items": items}

    def pick(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        queue_key = str(payload.get("name_key", "") or "").strip()
        oid = self.normalize_onliner_id(payload.get("onliner_id", ""))
        url = str(payload.get("url", "") or "").strip()
        name = str(payload.get("name", "") or "").strip()
        if not queue_key:
            return {"status": "error", "message": "name_key обязателен"}, 400

        queue = self.load_review_queue()
        entry = dict(queue.get(queue_key, {}) or {})
        base_key = match_name_key(queue_key, entry)
        payload_supplier = str(payload.get("supplier", "") or "").strip()
        if payload_supplier and not entry.get("supplier"):
            entry["supplier"] = payload_supplier
        if not name:
            name = str(entry.get("name", "") or "").strip()

        if oid:
            supplier_names = unique_supplier_names(entry)
            manual_bindings = self.load_manual_id_bindings()
            conflict = None
            if supplier_names:
                conflict = manual_binding_id_conflict(
                    manual_bindings,
                    base_key,
                    oid,
                    supplier_names,
                    normalize_onliner_id=self.normalize_onliner_id,
                    manual_binding_scoped_key=self.manual_binding_scoped_key,
                )
            if conflict:
                return {
                    "status": "error",
                    "message": (
                        "Этот OnlinerID уже закреплен в ручном кеше "
                        f"за другим товаром: {conflict}"
                    ),
                }, 409

            session_dir = self.get_active_session_dir()
            if supplier_names and session_dir:
                try:
                    frame = self.read_consolidated_json_fast_df(session_dir)
                    frame_conflict = dataframe_id_conflict_for_supplier(
                        frame,
                        base_key,
                        oid,
                        supplier_names,
                        normalize_name_key=self.normalize_name_key,
                        normalize_onliner_id=self.normalize_onliner_id,
                    )
                except Exception:
                    frame_conflict = None
                if frame_conflict:
                    supplier_label = str(
                        frame_conflict.get("supplier")
                        or supplier_names[0]
                        or "поставщика"
                    ).strip()
                    conflict_name = str(
                        frame_conflict.get("name")
                        or f"строка {frame_conflict.get('row_idx')}"
                    )
                    return {
                        "status": "error",
                        "message": (
                            f"Этот OnlinerID уже стоит у другого товара "
                            f"{supplier_label}: {conflict_name}"
                        ),
                    }, 409

            manual_record = {"id": oid, "url": url}
            if supplier_names:
                manual_record["suppliers"] = supplier_names
            manual_key = base_key
            if len(supplier_names) == 1:
                manual_key = (
                    self.manual_binding_scoped_key(
                        base_key, supplier_names[0]
                    )
                    or base_key
                )
            manual_bindings[manual_key] = manual_record
            self.save_manual_id_bindings(manual_bindings)

            if session_dir:
                self._apply_choice_to_session(
                    session_dir,
                    base_key=base_key,
                    supplier_names=supplier_names,
                    oid=oid,
                    url=url,
                    name=name,
                )

        queue.pop(queue_key, None)
        self.save_review_queue(queue)
        return {"status": "ok", "remaining": len(queue)}

    def clear(self):
        self.save_review_queue({})
        return {"status": "ok"}

    def _apply_choice_to_session(
        self,
        session_dir,
        *,
        base_key,
        supplier_names,
        oid,
        url,
        name,
    ):
        try:
            frame = self.read_consolidated_json_fast_df(session_dir)
            if "OnlinerID" not in frame.columns:
                frame["OnlinerID"] = ""
            if "Ссылка" not in frame.columns:
                frame["Ссылка"] = ""
            for row_idx, row in frame.iterrows():
                normalized_name = self.normalize_name_key(
                    str(row.get("Название", ""))
                )
                if normalized_name != base_key:
                    continue
                if supplier_names and not row_matches_supplier_names(
                    row, supplier_names
                ):
                    continue
                frame.at[row_idx, "OnlinerID"] = oid
                if url:
                    frame.at[row_idx, "Ссылка"] = url
            self.write_consolidated_json(
                frame, Path(session_dir) / "consolidated.json"
            )
            self.write_consolidated_df_background(
                session_dir, frame, label="review-queue-pick"
            )
            self.append_id_change_journal(
                {
                    "ts": int(self.clock()),
                    "action": "review_queue_pick",
                    "source": "api_review_queue_pick",
                    "changes": [
                        {
                            "name": name,
                            "new_onliner_id": oid,
                            "new_url": url,
                        }
                    ],
                }
            )
        except Exception:
            # Keep the existing behavior: a saved manual binding remains useful
            # even when the active session cannot be updated immediately.
            pass
