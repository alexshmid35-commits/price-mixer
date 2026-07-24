"""Canonical category repair for consolidated wire rows."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from price_mixer.product_schema import ProductField, ProductWireIndex


def json_row_needs_category_repair(
    name,
    raw_category,
    current_category,
    *,
    normalize_internal_category_name: Callable,
    canonical_ui_category_name: Callable,
    normalize_catalog_category_name: Callable,
    infer_category: Callable,
    should_repair_catalog_category: Callable,
):
    if not current_category:
        return True
    raw = str(raw_category or "").strip()
    if normalize_internal_category_name(raw) != raw:
        return True
    current = str(current_category or "").strip()
    text = str(name or "").strip().lower()
    text_without_prefix = re.sub(r"^\[[^\]]+\]\s*", "", text).strip()
    inferred = canonical_ui_category_name(normalize_catalog_category_name(infer_category(name)))
    if should_repair_catalog_category(current, inferred):
        return True
    if current != "Материнская плата" and re.search(
        r"^\s*(?:mb|motherboard|мат\s+плат|материнск)\b",
        text_without_prefix,
    ):
        return True
    if current in {"БУМАГА", "АКСЕССУАРЫ", "WEB", "РАЗВЕТВИТЕЛЬ", "НАБОР"}:
        return True
    if current in {"SSD", "Накопители USB", "Монитор"} and (
        "радиатор" in text
        or "охлажд" in text
        or "термопаст" in text
        or "web камера" in text
        or "webcam" in text
        or "разветвитель usb" in text
        or "usb hub" in text
        or "dvdrw" in text
        or "dvd-rw" in text
        or "набор" in text
        or "ssd" in text
        or "hdd" in text
        or "жестк" in text
        or "винчестер" in text
    ):
        return True
    if current in {"Монитор", "Периферия", "Аксессуары"} and ("кронштейн" in text):
        return True
    if (
        current == "Кронштейны"
        and "кронштейн" not in text
        and (
            "монитор" in text
            or "ips" in text
            or "hdmi" in text
            or "displayport" in text
            or "гц" in text
            or "hz" in text
            or re.search(r"\d{3,4}\s*x\s*\d{3,4}", text)
        )
    ):
        return True
    if current == "Кабели и переходники" and (
        "web" in text
        or "кам" in text
        or "клавиат" in text
        or "keyboard" in text
        or "науш" in text
        or "гарнитур" in text
        or "wi-fi" in text
        or "wifi" in text
        or "bluetooth" in text
        or "сетевой usb" in text
    ):
        return True
    if current == "Периферия" and (
        "монитор" in text or "мышь" in text or "mouse" in text or "клавиат" in text or "keyboard" in text
    ):
        return True
    if current == "Наушники" and ("колонки" in text or "акустик" in text or "soundbar" in text or "speaker" in text):
        return True
    if (
        current == "Системный блок"
        and re.search(
            r"\bddr[345]\b|оперативн|\bram\b|so[\s\-]?dimm|\bdimm\b",
            text_without_prefix,
        )
        and not re.search(
            r"\bкомпьютер\b|системный\s+блок|\bпэвм\b|\btgpc\b|"
            r"iven\s+(?:by|gaming|office|home|pro|ultra)|"
            r"\bcore\s+i[3579]\b|\bryzen\b",
            text_without_prefix,
        )
    ):
        return True
    if current in {"27", "24", "32"} and (
        "ips" in text or "hdmi" in text or "displayport" in text or "гц" in text or "hz" in text
    ):
        return True
    if current in {
        "Видеокарта",
        "SSD",
        "Процессор",
        "Оперативная память",
    } and ("компьютер" in text or "моноблок" in text or "системный блок" in text or "пэвм tgpc" in text):
        return True
    return current == "SSD" and "шасси" in text


@dataclass(frozen=True)
class CategoryRepairRuntime:
    read_rows: Callable
    compatibility_rows_reader: Callable
    cache_key: Callable
    get_cached_rows: Callable
    set_cached_rows: Callable
    load_visibility_map: Callable
    canonical_ui_category_name: Callable
    get_categories_by_ids: Callable
    get_categories_by_exact_names: Callable
    load_category_overrides: Callable
    load_manual_category_overrides: Callable
    supplier_visibility_known_categories: Callable
    normalize_internal_category_name: Callable
    repair_saved_category_for_product: Callable
    category_override_for_row: Callable
    looks_like_raw_supplier_category: Callable
    normalize_onliner_id: Callable
    native_catalog_category_for_product: Callable
    normalize_name_key: Callable
    raw_supplier_inferred_category_for_product: Callable
    strong_inferred_category_for_product: Callable
    sorting_review_category: Callable
    json_row_needs_repair: Callable
    row_category: Callable
    build_item_category_keys: Callable
    infer_category: Callable

    def correct_rows(self, session_dir, *, apply_visibility=True):
        json_path = Path(session_dir) / "consolidated.json"
        cache_key = self.cache_key(
            session_dir,
            json_path,
            apply_visibility,
        )
        cached_rows = self.get_cached_rows(cache_key)
        if cached_rows is not None:
            return cached_rows
        if apply_visibility:
            rows = self.correct_rows(session_dir, apply_visibility=False)
            if rows is None:
                return None
            visibility_map = self.load_visibility_map(session_dir)
            if visibility_map:
                hidden = {
                    self.canonical_ui_category_name(category)
                    for categories in visibility_map.values()
                    for category in categories
                    if str(category or "").strip()
                }
                rows = [
                    row for row in rows if self.canonical_ui_category_name(row[ProductWireIndex.CATEGORY]) not in hidden
                ]
            self.set_cached_rows(cache_key, rows)
            return rows

        rows = self.read_rows(
            session_dir,
            json_path,
            compatibility_rows_reader=self.compatibility_rows_reader,
        )
        if not rows or not all(len(row) >= 10 for row in rows):
            return None

        catalog_categories = self.get_categories_by_ids([row[ProductWireIndex.ONLINER_ID] for row in rows])
        exact_name_categories = self.get_categories_by_exact_names([row[ProductWireIndex.NAME] for row in rows])
        overrides = self.load_category_overrides()
        explicit_overrides = self.load_manual_category_overrides()
        known_raw_categories = self.supplier_visibility_known_categories()
        corrected = []
        for source_row in rows:
            row = source_row
            current = self.normalize_internal_category_name(row[ProductWireIndex.CATEGORY])
            category_name = current
            item = {
                ProductField.NAME: row[ProductWireIndex.NAME],
                ProductField.SUPPLIER: row[ProductWireIndex.SUPPLIER],
                ProductField.CATEGORY: current,
            }
            explicit = self.repair_saved_category_for_product(
                self.category_override_for_row(item, explicit_overrides),
                row[ProductWireIndex.NAME],
            )
            manual = self.repair_saved_category_for_product(
                self.category_override_for_row(item, overrides),
                row[ProductWireIndex.NAME],
            )
            if self.looks_like_raw_supplier_category(explicit):
                explicit = ""
            if self.looks_like_raw_supplier_category(manual):
                manual = ""
            onliner_id = self.normalize_onliner_id(row[ProductWireIndex.ONLINER_ID])
            product_name = row[ProductWireIndex.NAME]
            catalog = self.native_catalog_category_for_product(
                catalog_categories.get(onliner_id, ""),
                product_name,
            )
            exact = self.native_catalog_category_for_product(
                exact_name_categories.get(
                    self.normalize_name_key(product_name),
                    "",
                ),
                product_name,
            )
            raw_inferred = ""
            if self.looks_like_raw_supplier_category(current):
                raw_inferred = self.raw_supplier_inferred_category_for_product(
                    product_name,
                    known_raw_categories,
                )
            if onliner_id and catalog:
                category_name = catalog
            elif exact:
                category_name = exact
            elif explicit:
                category_name = explicit
            elif onliner_id:
                category_name = self.strong_inferred_category_for_product(product_name) or self.sorting_review_category(
                    current
                )
            elif raw_inferred:
                category_name = raw_inferred
            elif manual:
                category_name = manual
            elif self.json_row_needs_repair(
                product_name,
                row[ProductWireIndex.CATEGORY],
                current,
            ):
                category_name = self.normalize_internal_category_name(
                    self.row_category(
                        {
                            ProductField.NAME: product_name,
                            ProductField.SUPPLIER: row[ProductWireIndex.SUPPLIER],
                            ProductField.CATEGORY: current,
                        },
                        overrides={},
                        build_item_category_keys=self.build_item_category_keys,
                        infer_category=self.infer_category,
                    )
                )
            category_name = self.canonical_ui_category_name(category_name)
            if self.looks_like_raw_supplier_category(category_name):
                category_name = self.sorting_review_category(category_name)
            if category_name != row[ProductWireIndex.CATEGORY]:
                row = list(row)
                row[ProductWireIndex.CATEGORY] = category_name
            corrected.append(row)

        self.set_cached_rows(cache_key, corrected)
        return corrected
