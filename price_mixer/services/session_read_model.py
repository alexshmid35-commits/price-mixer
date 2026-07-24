"""Revision-cached dashboard read model for consolidated sessions."""

from __future__ import annotations

import copy
import math
import threading
from collections import OrderedDict

from price_mixer.product_schema import ProductWireIndex


class SessionReadModel:
    """Cache expensive dashboard projections by canonical session revision."""

    def __init__(self, *, store=None, max_entries=12):
        self.store = store
        self.max_entries = max(1, int(max_entries))
        self._lock = threading.RLock()
        self._cache = OrderedDict()
        self._inflight = {}

    def get_or_build(self, session_dir, revision_token, builder):
        key = (str(session_dir), revision_token)
        while True:
            with self._lock:
                cached = self._cache.get(key)
                if cached is not None:
                    self._cache.move_to_end(key)
                    return copy.deepcopy(cached)
                event = self._inflight.get(key)
                if event is None:
                    event = threading.Event()
                    self._inflight[key] = event
                    break
            event.wait()

        try:
            if self.store is not None:
                persistent = self.store.read_dashboard_projection(
                    session_dir,
                    revision_token,
                )
                if persistent is not None:
                    self._store_memory(key, persistent)
                    return copy.deepcopy(persistent)
            payload = dict(builder() or {})
            if self.store is not None and payload:
                self.store.write_dashboard_projection(
                    session_dir,
                    revision_token,
                    payload,
                )
            self._store_memory(key, payload)
            return payload
        finally:
            with self._lock:
                completed = self._inflight.pop(key, None)
                if completed is not None:
                    completed.set()

    def invalidate(self, session_dir=None):
        with self._lock:
            if session_dir is None:
                self._cache.clear()
                return
            target = str(session_dir)
            for key in [key for key in self._cache if key[0] == target]:
                self._cache.pop(key, None)

    def _store_memory(self, key, payload):
        with self._lock:
            self._cache[key] = copy.deepcopy(payload)
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)


def build_dashboard_payload(
    *,
    full_rows,
    visible_rows,
    export_rows,
    hidden_categories,
    normalize_onliner_id,
    normalize_category,
    category_sort_key,
):
    """Build all result-page counters in one projection pass."""
    rows = [row for row in full_rows or [] if isinstance(row, list)]
    visible = [row for row in visible_rows or [] if isinstance(row, list)]
    suppliers = set()
    id_counts: dict[str, int] = {}
    without_id_counts: dict[str, int] = {}

    for row in rows:
        supplier = _wire_text(row, ProductWireIndex.SUPPLIER)
        if supplier:
            suppliers.add(supplier)
        onliner_id = normalize_onliner_id(_wire_value(row, ProductWireIndex.ONLINER_ID))
        if onliner_id:
            id_counts[onliner_id] = int(id_counts.get(onliner_id, 0)) + 1
            continue
        category = _normalized_category(row, normalize_category)
        without_id_counts[category] = int(without_id_counts.get(category, 0)) + 1

    normalized_hidden = {
        normalize_category(category) or "Без категории"
        for category in hidden_categories or set()
        if str(category or "").strip()
    }
    hidden_counts: dict[str, int] = {}
    if normalized_hidden:
        for row in rows:
            category = _normalized_category(row, normalize_category)
            if category in normalized_hidden:
                hidden_counts[category] = int(hidden_counts.get(category, 0)) + 1

    export_category_counts: dict[str, int] = {}
    suspicious_price_count = 0
    for item in export_rows or []:
        category = normalize_category(item.get("category", "")) or "Без категории"
        export_category_counts[category] = int(export_category_counts.get(category, 0)) + 1
        source_position = item.get("key")
        try:
            source_row = visible[int(source_position)]
        except (IndexError, TypeError, ValueError):
            source_row = None
        if source_row is not None and _has_price_issue(source_row):
            suspicious_price_count += 1

    without_id = int(sum(without_id_counts.values()))
    total = int(len(rows))
    duplicate_id_rows = int(sum(count for count in id_counts.values() if count > 1))
    hidden_category_counts = _format_counts(hidden_counts, category_sort_key)
    return {
        "total": total,
        "suppliers": int(len(suppliers)),
        "consolidated": total,
        "matched": total - without_id,
        "with_id": total - without_id,
        "without_id": without_id,
        "duplicate_id_rows": duplicate_id_rows,
        "export_rows": int(len(export_rows or [])),
        "export_category_counts": _format_counts(export_category_counts, category_sort_key),
        "without_id_category_counts": _format_counts(without_id_counts, category_sort_key),
        "hidden_rows": int(sum(hidden_counts.values())),
        "hidden_category_counts": hidden_category_counts,
        "quality_suspicious_price_count": int(suspicious_price_count),
    }


def result_context(dashboard, *, show_checks_block, snapshot_diff):
    payload = dict(dashboard or {})
    payload["show_checks_block"] = bool(show_checks_block)
    payload["snapshot_diff"] = snapshot_diff
    return payload


def stats_context(dashboard, *, snapshot_diff):
    payload = dict(dashboard or {})
    new_without_id_count = int((snapshot_diff or {}).get("new_without_id_count", 0) or 0)
    payload["new_without_id_count"] = new_without_id_count
    payload["id_pick_badge_count"] = (
        new_without_id_count if new_without_id_count > 0 else int(payload.get("without_id", 0) or 0)
    )
    return payload


def _wire_value(row, index):
    position = int(index)
    return row[position] if len(row) > position else ""


def _wire_text(row, index):
    return str(_wire_value(row, index) or "").strip()


def _normalized_category(row, normalize_category):
    category = normalize_category(_wire_text(row, ProductWireIndex.CATEGORY))
    return category or "Без категории"


def _format_counts(counts, category_sort_key):
    items = [
        {"category": str(category or "Без категории"), "count": int(count or 0)}
        for category, count in (counts or {}).items()
        if int(count or 0) > 0
    ]
    items.sort(key=lambda item: category_sort_key(str(item["category"])))
    return items


def _has_price_issue(row):
    price = _number(_wire_value(row, ProductWireIndex.PRICE))
    rrc = _number(_wire_value(row, ProductWireIndex.RRC))
    if price is None or price <= 0 or rrc is None or rrc <= 0:
        return True
    margin = rrc - price
    if margin <= 0:
        return True
    margin_pct = (margin / price) * 100.0
    return margin < 20.0 and margin_pct < 5.0


def _number(value):
    text = str(value or "").strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
