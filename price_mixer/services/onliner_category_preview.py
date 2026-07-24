"""Onliner category structure preview payloads."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def collect_onliner_ids(df, *, normalize_onliner_id: Callable[[Any], str]) -> list[str]:
    if df is None or "OnlinerID" not in df.columns:
        return []
    ids = []
    for value in df["OnlinerID"].tolist():
        oid = normalize_onliner_id(value)
        if oid:
            ids.append(oid)
    return sorted(set(ids))


def build_onliner_category_preview_payload(
    df,
    *,
    catalog_categories: Mapping[str, str],
    markups: Mapping[str, Any],
    normalize_onliner_id: Callable[[Any], str],
    normalize_catalog_category_name: Callable[[Any], str],
) -> dict:
    if df is None or df.empty:
        return {"status": "ok", "summary": {}, "categories": [], "transitions": []}

    transition_counts = {}
    transition_examples = {}
    category_counts = {}
    category_changes = {}
    category_examples = {}
    with_id = 0
    mapped = 0
    missing_catalog_category = 0
    changed = 0
    without_id = 0

    for _, row in df.iterrows():
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if not oid:
            without_id += 1
            continue
        with_id += 1
        target_category = normalize_catalog_category_name(catalog_categories.get(oid, ""))
        if not target_category:
            missing_catalog_category += 1
            continue
        mapped += 1
        current_category = str(row.get("Категория", "") or "").strip() or "Без категории"
        product_name = str(row.get("Название", "") or "").strip()
        category_counts[target_category] = category_counts.get(target_category, 0) + 1
        if len(category_examples.get(target_category, [])) < 4 and product_name:
            category_examples.setdefault(target_category, []).append(product_name)
        if current_category != target_category:
            changed += 1
            category_changes[target_category] = category_changes.get(target_category, 0) + 1
            key = (current_category, target_category)
            transition_counts[key] = transition_counts.get(key, 0) + 1
            if len(transition_examples.get(key, [])) < 3 and product_name:
                transition_examples.setdefault(key, []).append(product_name)

    categories = [
        {
            "name": name,
            "count": count,
            "changed": int(category_changes.get(name, 0)),
            "has_markup": name in markups,
            "examples": category_examples.get(name, []),
        }
        for name, count in sorted(category_counts.items(), key=lambda item: (-item[1], item[0].lower()))
    ]
    transitions = [
        {
            "from": source,
            "to": target,
            "count": count,
            "examples": transition_examples.get((source, target), []),
        }
        for (source, target), count in sorted(
            transition_counts.items(),
            key=lambda item: (-item[1], item[0][0].lower(), item[0][1].lower()),
        )
    ]
    return {
        "status": "ok",
        "summary": {
            "total": int(len(df)),
            "with_id": with_id,
            "without_id": without_id,
            "mapped": mapped,
            "missing_catalog_category": missing_catalog_category,
            "changed": changed,
            "unchanged": mapped - changed,
            "categories": len(categories),
            "categories_without_markup": sum(1 for item in categories if not item["has_markup"]),
        },
        "categories": categories,
        "transitions": transitions,
    }
