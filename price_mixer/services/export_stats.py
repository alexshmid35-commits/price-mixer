"""Fast export/statistics counters for JSON snapshots."""

import math


def export_row_count_from_json_rows(
    json_rows,
    settings,
    *,
    normalize_onliner_id,
    normalize_name_key,
    normalize_supplier_name_list,
    is_pc_export_row,
):
    return int(len(export_rows_from_json_rows(
        json_rows,
        settings,
        normalize_onliner_id=normalize_onliner_id,
        normalize_name_key=normalize_name_key,
        normalize_supplier_name_list=normalize_supplier_name_list,
        is_pc_export_row=is_pc_export_row,
    )))


def export_category_counts_from_json_rows(
    json_rows,
    settings,
    *,
    normalize_onliner_id,
    normalize_name_key,
    normalize_supplier_name_list,
    is_pc_export_row,
    category_sort_key,
):
    counts = {}
    for row in export_rows_from_json_rows(
        json_rows,
        settings,
        normalize_onliner_id=normalize_onliner_id,
        normalize_name_key=normalize_name_key,
        normalize_supplier_name_list=normalize_supplier_name_list,
        is_pc_export_row=is_pc_export_row,
    ):
        category = str(row.get("category", "") or "").strip() or "Без категории"
        counts[category] = int(counts.get(category, 0)) + 1
    return format_category_counts(counts, category_sort_key=category_sort_key)


def without_id_category_counts_from_json_rows(json_rows, *, normalize_onliner_id, category_sort_key):
    counts = {}
    for row in json_rows or []:
        if not isinstance(row, list):
            continue
        oid = normalize_onliner_id(row[0] if len(row) > 0 else "")
        if oid:
            continue
        category = str(row[9] if len(row) > 9 else "").strip() or "Без категории"
        counts[category] = int(counts.get(category, 0)) + 1
    return format_category_counts(counts, category_sort_key=category_sort_key)


def without_id_category_counts_from_df(df, *, normalize_onliner_id, category_sort_key):
    counts = {}
    if df is None or getattr(df, "empty", True):
        return []
    for _, row in df.iterrows():
        if normalize_onliner_id(row.get("OnlinerID", "")):
            continue
        category = str(row.get("Категория", "") or "").strip() or "Без категории"
        counts[category] = int(counts.get(category, 0)) + 1
    return format_category_counts(counts, category_sort_key=category_sort_key)


def format_category_counts(counts, *, category_sort_key):
    items = [
        {"category": str(category or "Без категории"), "count": int(count or 0)}
        for category, count in (counts or {}).items()
        if int(count or 0) > 0
    ]
    items.sort(key=lambda item: category_sort_key(str(item["category"])))
    return items


def export_rows_from_json_rows(
    json_rows,
    settings,
    *,
    normalize_onliner_id,
    normalize_name_key,
    normalize_supplier_name_list,
    is_pc_export_row,
):
    export_cfg = (settings or {}).get("export", {})
    include_without_id = bool(export_cfg.get("include_without_id", False))
    keep_lowest_id_price = bool(export_cfg.get("keep_lowest_price_per_onliner_id", True))
    exclude_category_prefixes = normalize_prefixes(export_cfg.get("exclude_category_prefixes", []))
    exclude_name_contains = normalize_contains_patterns(export_cfg.get("exclude_name_contains", []))
    allowed_categories = normalize_allowed_categories(export_cfg.get("allowed_categories", []))
    duplicate_filter_suppliers = {
        item.strip().lower()
        for item in normalize_supplier_name_list(export_cfg.get("exclude_duplicate_id_suppliers", []))
        if item.strip()
    }
    only_pc_suppliers = {
        item.strip().lower()
        for item in normalize_supplier_name_list(export_cfg.get("only_pc_suppliers", []))
        if item.strip()
    }

    rows = []
    for pos, raw in enumerate(json_rows or []):
        if not isinstance(raw, list):
            continue
        oid = normalize_onliner_id(raw[0] if len(raw) > 0 else "")
        if not include_without_id and not oid:
            continue
        category = str(raw[9] if len(raw) > 9 else "").strip()
        if exclude_category_prefixes and starts_with_any_prefix(category, exclude_category_prefixes):
            continue
        if allowed_categories and category.casefold() not in allowed_categories:
            continue
        name = str(raw[1] if len(raw) > 1 else "").strip()
        if exclude_name_contains and contains_any_pattern(name, exclude_name_contains):
            continue
        try:
            row_idx = int(raw[8]) if len(raw) > 8 else pos
        except Exception:
            row_idx = pos
        rows.append({
            "key": pos,
            "row_idx": row_idx,
            "oid": oid,
            "name": name,
            "price": export_count_price(raw[2] if len(raw) > 2 else ""),
            "supplier": str(raw[3] if len(raw) > 3 else "").strip(),
            "category": category,
        })

    if keep_lowest_id_price:
        rows = export_count_keep_lowest_price(rows)
    if duplicate_filter_suppliers:
        rows = export_count_drop_duplicate_id_supplier_rows(rows, duplicate_filter_suppliers, normalize_name_key)
    if only_pc_suppliers:
        rows = export_count_keep_only_pc_supplier_rows(rows, only_pc_suppliers, is_pc_export_row)
    return rows


def normalize_prefixes(value):
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value or "").replace("\r", "\n").split("\n")
    prefixes = []
    for item in raw_items:
        prefix = str(item or "").strip().casefold()
        if prefix and prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def starts_with_any_prefix(value, prefixes):
    text = str(value or "").strip().casefold()
    return bool(text) and any(text.startswith(prefix) for prefix in prefixes)


def normalize_contains_patterns(value):
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value or "").replace("\r", "\n").split("\n")
    patterns = []
    for item in raw_items:
        pattern = str(item or "").strip().casefold()
        if pattern and pattern not in patterns:
            patterns.append(pattern)
    return patterns


def contains_any_pattern(value, patterns):
    text = str(value or "").strip().casefold()
    return bool(text) and any(pattern in text for pattern in patterns)


def normalize_allowed_categories(value):
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value or "").replace("\r", "\n").split("\n")
    return {
        str(item or "").strip().casefold()
        for item in raw_items
        if str(item or "").strip()
    }


def export_count_price(value):
    text = str(value or "").strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        price = float(text)
        return price if math.isfinite(price) else None
    except Exception:
        return None


def export_count_keep_lowest_price(rows):
    by_oid = {}
    for row in rows:
        oid = row.get("oid", "")
        if oid:
            by_oid.setdefault(oid, []).append(row)
    drop_keys = set()
    for group in by_oid.values():
        if len(group) < 2:
            continue
        priced = [row for row in group if row.get("price") is not None]
        if priced:
            keep_key = min(priced, key=lambda row: (float(row["price"]), row["key"]))["key"]
        else:
            keep_key = min(group, key=lambda row: row["key"])["key"]
        drop_keys.update(row["key"] for row in group if row["key"] != keep_key)
    if not drop_keys:
        return rows
    return [row for row in rows if row["key"] not in drop_keys]


def export_count_drop_duplicate_id_supplier_rows(rows, supplier_lookup, normalize_name_key):
    by_oid = {}
    for row in rows:
        oid = row.get("oid", "")
        name_key = normalize_name_key(row.get("name", ""))
        if oid and name_key:
            item = dict(row)
            item["name_key"] = name_key
            by_oid.setdefault(oid, []).append(item)
    drop_keys = set()
    for group in by_oid.values():
        if len(group) < 2:
            continue
        distinct_names = {row["name_key"] for row in group if row.get("name_key")}
        if len(distinct_names) < 2:
            continue
        for row in group:
            if str(row.get("supplier", "")).strip().lower() in supplier_lookup:
                drop_keys.add(row["key"])
    if not drop_keys:
        return rows
    return [row for row in rows if row["key"] not in drop_keys]


def export_count_keep_only_pc_supplier_rows(rows, supplier_lookup, is_pc_export_row):
    kept = []
    for row in rows:
        supplier = str(row.get("supplier", "")).strip().lower()
        if supplier not in supplier_lookup:
            kept.append(row)
            continue
        export_row = {
            "Название": row.get("name", ""),
            "Поставщик": row.get("supplier", ""),
            "Категория": row.get("category", ""),
        }
        if is_pc_export_row(export_row):
            kept.append(row)
    return kept
