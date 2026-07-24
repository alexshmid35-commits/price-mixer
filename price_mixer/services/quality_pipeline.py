"""Quality-check helpers shared by export and UI flows."""

import math


def apply_quality_visibility_filter(
    df,
    session_dir,
    *,
    apply_visibility_filter,
    load_visibility_map,
    normalize_category,
):
    """Suppress globally hidden product types from quality warnings."""
    filtered = apply_visibility_filter(df, session_dir)
    if filtered.empty or "Категория" not in filtered.columns:
        return filtered

    hidden_categories = {
        normalize_category(category)
        for categories in load_visibility_map(session_dir).values()
        for category in categories
    }
    hidden_categories.discard("")
    if not hidden_categories:
        return filtered

    mask = filtered["Категория"].apply(lambda category: normalize_category(category) not in hidden_categories)
    return filtered[mask].copy()


def hidden_categories_from_visibility_map(visibility_map, *, normalize_category):
    hidden_categories = {
        normalize_category(category)
        for categories in (visibility_map or {}).values()
        for category in categories
    }
    hidden_categories.discard("")
    return hidden_categories


def count_suspicious_price_rows_from_json(
    rows,
    *,
    hidden_categories=None,
    normalize_category,
    allowed_categories=None,
    exclude_category_prefixes=None,
    require_onliner_id=False,
    has_onliner_id=None,
):
    hidden_categories = set(hidden_categories or [])
    allowed_categories = {
        normalize_category(category)
        for category in (allowed_categories or [])
        if normalize_category(category)
    }
    exclude_category_prefixes = [
        str(prefix or "").strip().casefold()
        for prefix in (exclude_category_prefixes or [])
        if str(prefix or "").strip()
    ]
    suspicious_price_count = 0

    for row in rows or []:
        if require_onliner_id:
            raw_id = row[0] if len(row) > 0 else ""
            if has_onliner_id is not None:
                if not has_onliner_id(raw_id):
                    continue
            elif str(raw_id or "").strip().casefold() in {"", "нет", "none", "nan"}:
                continue

        category = row[9] if len(row) > 9 else ""
        normalized_category = normalize_category(category)
        raw_category = str(category or "").strip().casefold()
        if normalized_category in hidden_categories:
            continue
        if exclude_category_prefixes and any(raw_category.startswith(prefix) for prefix in exclude_category_prefixes):
            continue
        if allowed_categories and normalized_category not in allowed_categories:
            continue

        try:
            price = float(row[2]) if len(row) > 2 and str(row[2]).strip() != "" else float("nan")
            retail = float(row[6]) if len(row) > 6 and str(row[6]).strip() != "" else float("nan")
        except Exception:
            price = float("nan")
            retail = float("nan")

        if not math.isfinite(price) or price <= 0 or not math.isfinite(retail) or retail <= 0:
            suspicious_price_count += 1
            continue

        margin_abs = float(retail - price)
        margin_pct = float((margin_abs / price) * 100.0) if price > 0 else -999.0
        if margin_abs <= 0 or (margin_abs < 20.0 and margin_pct < 5.0):
            suspicious_price_count += 1

    return suspicious_price_count
