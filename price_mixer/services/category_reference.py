"""Category and supplier reference payload builders."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

import pandas as pd


def _clean_supplier_item_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def build_categories_payload(
    df: pd.DataFrame | None,
    *,
    normalize_category: Callable[[Any], str],
    normalize_onliner_id: Callable[[Any], str],
    category_sort_key: Callable[[str], tuple],
) -> dict:
    if df is None or df.empty or "Название" not in df.columns:
        return {"categories": []}

    category_counts = {}
    category_without_id = {}
    for _, row in df.iterrows():
        category = normalize_category(row.get("Категория", ""))
        if not category:
            continue
        category_counts[category] = category_counts.get(category, 0) + 1
        if not normalize_onliner_id(row.get("OnlinerID", "")):
            category_without_id[category] = category_without_id.get(category, 0) + 1

    return {
        "categories": [
            {"name": name, "count": count, "without_id": int(category_without_id.get(name, 0))}
            for name, count in sorted(category_counts.items(), key=lambda x: category_sort_key(x[0]))
        ]
    }


def build_category_catalog_payload(
    *,
    priority_categories: Iterable[str],
    overrides: Mapping[str, str],
    markups: Mapping[str, Any],
    df: pd.DataFrame | None,
    row_category: Callable[[Any, Mapping[str, str]], str],
    normalize_category: Callable[[Any], str],
    is_sorting_review_category: Callable[[str], bool],
    category_sort_key: Callable[[str], tuple],
) -> dict:
    all_cats = {normalize_category(name) for name in priority_categories}
    all_cats.update(normalize_category(v) for v in overrides.values() if str(v).strip())
    all_cats.update(normalize_category(k) for k in markups.keys() if str(k).strip())
    if df is not None and not df.empty:
        for _, row in df.iterrows():
            all_cats.add(normalize_category(row_category(row, overrides)))
    all_cats = {name for name in all_cats if name and not is_sorting_review_category(name)}
    return {"categories": sorted(all_cats, key=category_sort_key)}


def build_suppliers_payload(df: pd.DataFrame | None) -> dict:
    if df is None or df.empty:
        return {"suppliers": []}
    return {
        "suppliers": sorted({
            str(s).strip()
            for s in df.get("Поставщик", pd.Series(dtype=str)).dropna().tolist()
            if str(s).strip()
        })
    }


def build_supplier_categories_payload(
    df: pd.DataFrame | None,
    *,
    supplier: str,
    visibility_map: Mapping[str, Iterable[str]],
    canonical_supplier_name: Callable[[Any], str],
    normalize_category: Callable[[Any], str],
    is_sorting_review_category: Callable[[str], bool],
    category_sort_key: Callable[[str], tuple],
    include_category: Callable[[str], bool] | None = None,
) -> dict:
    supplier = str(supplier or "").strip()
    if df is None or df.empty or "Категория" not in df.columns:
        return {"categories": []}

    hidden_set = {
        normalize_category(name)
        for categories in (visibility_map or {}).values()
        for name in categories
        if normalize_category(name)
    }

    counts = {}
    examples = {}
    products = {}
    search_terms = {}
    search_seen = {}
    for _, row in df.iterrows():
        cat = normalize_category(row.get("Категория", ""))
        if not cat or is_sorting_review_category(cat):
            continue
        if callable(include_category) and not include_category(cat):
            continue
        product_name = _clean_supplier_item_value(row.get("Название", ""))
        counts[cat] = counts.get(cat, 0) + 1
        if product_name:
            seen = search_seen.setdefault(cat, set())
            search_key = product_name.casefold()
            if search_key not in seen:
                seen.add(search_key)
                search_terms.setdefault(cat, []).append(product_name)
        if len(examples.get(cat, [])) < 8:
            if product_name:
                examples.setdefault(cat, []).append(product_name)
        category_products = products.setdefault(cat, [])
        if len(category_products) < 20:
            category_products.append({
                "name": product_name,
                "wholesale": _clean_supplier_item_value(row.get("Цена", "")),
                "rrc": _clean_supplier_item_value(row.get("РРЦ", "")),
                "no_discount": _clean_supplier_item_value(row.get("Цена без скидки", "")),
            })

    items = []
    for name, count in counts.items():
        items.append({
            "name": name,
            "count": count,
            "hidden": name in hidden_set,
            "examples": examples.get(name, []),
            "items": products.get(name, []),
            "search_text": " ".join(search_terms.get(name, [])),
        })
    items.sort(key=lambda x: (1 if x.get("hidden") else 0, category_sort_key(str(x.get("name", "")).strip())))
    return {"status": "ok", "categories": items}
