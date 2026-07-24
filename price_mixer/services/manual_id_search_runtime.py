"""Specialized candidate selection for the manual Onliner ID picker."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from price_mixer.product_schema import ProductField

EXPLICIT_PREFIX_CATEGORIES = frozenset(
    {
        "Веб-камеры",
        "МФУ",
        "Клавиатура",
        "Мышь",
        "Наушники",
        "Микрофоны",
        "Акустика",
        "Накопители USB",
    }
)

MODE_BY_CATEGORY = {
    "Процессор": "cpu",
    "Материнская плата": "board",
    "Монитор": "monitor",
    "Видеокарта": "gpu",
    "Оперативная память": "ram",
    "SSD": "ssd",
    "Блок питания": "psu",
    "Корпус": "case",
    "Жесткий диск": "hdd",
    "Кулер": "cooler",
    "Кулеры": "cooler",
    "Охлаждение": "cooler",
    "Принтер": "printer",
    "Принтеры": "printer",
    "Принтер и МФУ": "printer",
    "МФУ": "printer",
    "Картриджи": "printer",
    "Клавиатура": "peripheral",
    "Мышь": "peripheral",
    "Наушники": "peripheral",
    "Акустика": "peripheral",
}

STRICT_PERIPHERAL_CATEGORIES = frozenset(
    {
        "Клавиатура",
        "Мышь",
        "Наушники",
        "Акустика",
    }
)


@dataclass(frozen=True)
class ManualIdSearchRuntime:
    normalize_catalog_category_name: Callable
    infer_category: Callable
    normalized_category_from_name: Callable
    is_iven_pc_name: Callable
    is_tgpc_pc_name: Callable
    is_iven_laptop_name: Callable
    search_iven_pc_candidates: Callable
    search_tgpc_pc_candidates: Callable
    supplier_laptop_candidates: Callable
    is_iven_laptop_candidate: Callable
    get_review_handler: Callable
    clock: Callable[[], float]

    def candidates(self, local_name, category="", top_n=12):
        name = str(local_name or "").strip()
        if not name:
            return []
        limit = max(1, int(top_n or 12))
        normalized_category = self.normalize_catalog_category_name(
            str(category or self.infer_category(name) or "").strip()
        )
        prefix_category = self.normalized_category_from_name(name)
        if prefix_category in EXPLICIT_PREFIX_CATEGORIES:
            normalized_category = prefix_category

        if self.is_iven_pc_name(name):
            return self.search_iven_pc_candidates(name, limit=limit)
        if self.is_tgpc_pc_name(name):
            return self.search_tgpc_pc_candidates(name, limit=limit)
        if self.is_iven_laptop_name(name, normalized_category):
            return self.supplier_laptop_candidates(
                name,
                top_n=limit,
                candidate_filter=self.is_iven_laptop_candidate,
                source_label="manual_laptop_db",
            )

        mode = MODE_BY_CATEGORY.get(normalized_category)
        if not mode:
            return []
        handler = self.get_review_handler(mode)
        row = {ProductField.SUPPLIER: "manual"}
        if not handler.is_target(row, name, normalized_category):
            return []
        result = (
            handler.build_row_result(
                0,
                row,
                name,
                normalized_category,
                int(self.clock()),
            )
            or {}
        )
        queue_candidates = (result.get("queue_item") or {}).get("candidates") or []
        report_candidates = (result.get("report_item") or {}).get("candidates") or []
        candidates = list(queue_candidates or report_candidates)
        if mode == "peripheral" and normalized_category in STRICT_PERIPHERAL_CATEGORIES:
            candidates = [
                candidate
                for candidate in candidates
                if self.normalize_catalog_category_name(
                    self.infer_category(str((candidate or {}).get("name", "") or ""))
                )
                == normalized_category
            ]
        return candidates[:limit]
