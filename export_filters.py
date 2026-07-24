"""Export DataFrame filters for duplicate IDs, lowest prices, and PC-only exports."""

import re

import numpy as np
import pandas as pd

from price_mixer.services.product_normalization import normalize_name_key, normalize_onliner_id


def normalize_supplier_name_list(value):
    raw_items = value if isinstance(value, list) else re.split(r"[\r\n,;]+", str(value or ""))
    out = []
    seen = set()
    for item in raw_items:
        name = str(item or "").strip()
        low = name.lower()
        if not name or low in seen:
            continue
        seen.add(low)
        out.append(name[:80])
    return out


def build_duplicate_onliner_id_issues(
    df,
    load_product_cache=None,
    is_manually_confirmed_id=None,
    row_category=None,
):
    if "OnlinerID" not in df.columns:
        return 0, []

    row_category = row_category or (lambda row: row.get("Категория", ""))
    is_manually_confirmed_id = is_manually_confirmed_id or (lambda name, oid: False)

    grouped = {}
    for index, row in df.iterrows():
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if not oid:
            continue
        name = str(row.get("Название", "")).strip()
        name_key = normalize_name_key(name)
        if not name_key:
            continue
        grouped.setdefault(oid, []).append({
            "row_idx": int(index),
            "name": name,
            "name_key": name_key,
            "supplier": str(row.get("Поставщик", "")).strip(),
            "category": str(row_category(row)).strip(),
        })

    product_cache = load_product_cache() if callable(load_product_cache) else {}
    issues = []
    problem_ids = 0
    for oid, rows in grouped.items():
        if len(rows) < 2:
            continue
        distinct_name_map = _distinct_names_by_key(rows)
        if len(distinct_name_map) < 2:
            continue

        confirmed_rows = []
        pending_rows = []
        for item in rows:
            if is_manually_confirmed_id(item.get("name", ""), oid):
                confirmed_rows.append(item)
            else:
                pending_rows.append(item)
        if pending_rows:
            rows_for_review = pending_rows
        else:
            continue

        problem_ids += 1
        cached_info = product_cache.get(oid) if isinstance(product_cache, dict) else {}
        api_name = str((cached_info or {}).get("name", "")).strip()
        api_url = str((cached_info or {}).get("url", "")).strip()
        for item in rows_for_review:
            issues.append(_duplicate_issue_item(
                item,
                oid,
                api_name,
                api_url,
                problem_ids,
                rows,
                distinct_name_map,
                confirmed_rows,
            ))

    issues.sort(key=lambda item: (str(item.get("onliner_id") or ""), str(item.get("name") or "").lower()))
    return int(problem_ids), issues


def apply_export_duplicate_id_filter(
    df,
    supplier_names=None,
    load_product_cache=None,
    is_manually_confirmed_id=None,
    row_category=None,
):
    supplier_list = normalize_supplier_name_list(supplier_names or [])
    if df is None or df.empty or not supplier_list:
        return df
    supplier_lookup = {name.strip().lower() for name in supplier_list if str(name or "").strip()}
    if not supplier_lookup:
        return df

    _, issues = build_duplicate_onliner_id_issues(
        df,
        load_product_cache=load_product_cache,
        is_manually_confirmed_id=is_manually_confirmed_id,
        row_category=row_category,
    )
    if not issues:
        return df

    drop_indexes = set()
    for issue in issues:
        supplier = str(issue.get("supplier") or "").strip().lower()
        row_idx = issue.get("row_idx")
        if supplier in supplier_lookup and isinstance(row_idx, int):
            drop_indexes.add(int(row_idx))
    if not drop_indexes:
        return df
    return df.drop(index=list(drop_indexes), errors="ignore").copy()


def apply_export_keep_lowest_price_per_onliner_id(df):
    if df is None or df.empty:
        return df
    id_col = "OnlinerID" if "OnlinerID" in df.columns else ("onliner_id" if "onliner_id" in df.columns else None)
    if not id_col:
        return df
    price_col = "Цена" if "Цена" in df.columns else ("price" if "price" in df.columns else None)

    temp = df.copy()
    temp["_oid_norm"] = temp[id_col].apply(normalize_onliner_id)
    has_id_mask = temp["_oid_norm"].astype(str) != ""
    if not has_id_mask.any():
        return df
    if price_col:
        raw_prices = (
            temp[price_col]
            .astype(str)
            .str.replace("\xa0", "", regex=False)
            .str.replace(" ", "", regex=False)
            .str.replace(",", ".", regex=False)
        )
        temp["_price_num"] = pd.to_numeric(raw_prices, errors="coerce")
    else:
        temp["_price_num"] = np.nan

    temp["_orig_pos"] = np.arange(len(temp))
    temp["_price_sort"] = temp["_price_num"].where(temp["_price_num"].notna(), np.inf)
    keep_idx = set(
        temp[has_id_mask]
        .sort_values(["_oid_norm", "_price_sort", "_orig_pos"], kind="mergesort")
        .drop_duplicates("_oid_norm", keep="first")
        .index
    )
    drop_mask = has_id_mask & ~temp.index.isin(keep_idx)
    if not drop_mask.any():
        return df
    return df[~drop_mask].copy()


def is_pc_export_row(row, is_tgpc_pc_name=None, row_category=None):
    is_tgpc_pc_name = is_tgpc_pc_name or (lambda name: False)
    row_category = row_category or (lambda item: item.get("Категория", ""))

    name = str(row.get("Название", "") or row.get("product_name", "") or "").strip()
    low_name = name.lower()
    if is_tgpc_pc_name(name):
        return True
    if low_name.startswith("компьютер "):
        return True
    if low_name.startswith("пэвм "):
        return True
    if low_name.startswith("системный блок "):
        return True
    if "iven" in low_name and "компьютер" in low_name:
        return True
    category = str(row.get("Категория", "") or row.get("category", "") or row_category(row) or "").strip().lower()
    if any(token in category for token in [
        "пэвм",
        "системный блок",
        "компьютер",
        "компьютеры / tgpc",
        "готовые решения tgpc",
    ]):
        return True
    link = str(row.get("Ссылка", "") or row.get("url", "") or "").strip().lower()
    if any(token in link for token in ["/desktoppc/", "/computer/", "/monoblock/", "/nettop/"]):
        return True
    onliner_name = str(row.get("Onliner", "") or row.get("onliner_name", "") or "").strip().lower()
    if "iven" in onliner_name and ("superpower" in onliner_name or "gaming" in onliner_name):
        return True
    return False


def apply_export_only_pc_filter(df, supplier_names=None, is_tgpc_pc_name=None, row_category=None):
    supplier_list = normalize_supplier_name_list(supplier_names or [])
    if df is None or df.empty or not supplier_list:
        return df
    supplier_lookup = {name.strip().lower() for name in supplier_list if str(name or "").strip()}
    if not supplier_lookup:
        return df
    supplier_col = "Поставщик" if "Поставщик" in df.columns else ("supplier" if "supplier" in df.columns else None)
    if not supplier_col:
        return df
    keep_mask = df.apply(
        lambda row: (
            str(row.get(supplier_col, "") or "").strip().lower() not in supplier_lookup
            or is_pc_export_row(row, is_tgpc_pc_name=is_tgpc_pc_name, row_category=row_category)
        ),
        axis=1,
    )
    return df[keep_mask].copy()


def _distinct_names_by_key(rows):
    distinct_name_map = {}
    for item in rows:
        key = str(item.get("name_key") or "").strip()
        if key and key not in distinct_name_map:
            distinct_name_map[key] = str(item.get("name") or "").strip()
    return distinct_name_map


def _duplicate_issue_item(item, oid, api_name, api_url, problem_ids, rows, distinct_name_map, confirmed_rows):
    current_name = str(item.get("name") or "").strip()
    current_key = str(item.get("name_key") or "").strip()
    other_names = [name for key, name in distinct_name_map.items() if key != current_key and name]
    reason_parts = []
    if api_name:
        reason_parts.append(f"Текущий ID ведет на {api_name}")
    reason = f"Этот OnlinerID используется у {len(distinct_name_map)} разных товаров"
    if other_names:
        shown = ", ".join(other_names[:2])
        if len(other_names) > 2:
            shown += ", ..."
        reason += f": {shown}"
    if confirmed_rows:
        reason += f". Уже подтверждено вручную: {len(confirmed_rows)}"
    reason_parts.append(reason)

    return {
        "row_idx": int(item.get("row_idx", -1)),
        "onliner_id": oid,
        "name": current_name,
        "supplier": str(item.get("supplier") or "").strip(),
        "category": str(item.get("category") or "").strip(),
        "api_name": api_name,
        "api_url": api_url,
        "score": 0.0,
        "reason": "duplicate_onliner_id",
        "reason_label": ". ".join(part for part in reason_parts if part),
        "status": "mismatch",
        "status_label": "Одинаковый ID",
        "duplicate_id_count": int(problem_ids),
        "duplicate_row_count": int(len(rows)),
        "duplicate_name_count": int(len(distinct_name_map)),
        "other_names": other_names[:4],
        "needs_review": True,
    }
