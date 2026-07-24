"""Build the Onliner ID comparison report payload."""

from __future__ import annotations

from typing import Callable, Mapping

import pandas as pd


def excel_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def build_id_compare_report_df(
    df: pd.DataFrame | None,
    products_by_id: Mapping[str, Mapping[str, object]],
    *,
    normalize_onliner_id: Callable[[object], str],
    calc_name_match: Callable[[str, str], Mapping[str, object]],
) -> pd.DataFrame:
    if df is None or df.empty or "OnlinerID" not in df.columns:
        return pd.DataFrame()

    rows = []
    for _, row in df.iterrows():
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if not oid:
            continue
        supplier_name = excel_text(row.get("Название", ""))
        product = products_by_id.get(oid)
        db_name = str((product or {}).get("name", "") or "").strip()
        db_id = str((product or {}).get("id", "") or "").strip()
        score = ""
        reason = ""
        if db_name:
            try:
                match = calc_name_match(supplier_name, db_name)
                score = round(float(match.get("score", 0.0) or 0.0) * 100, 1)
                reason = str(match.get("reason", "") or "")
            except Exception:
                score = ""
                reason = ""
        if not product:
            decision = "ID не найден"
            check_result = "ID не найден в базе"
            comment = "ID из прайса не найден в локальной базе Onliner."
            action = "Проверить ID / найти товар"
        elif isinstance(score, (int, float)) and score < 74:
            decision = "Проверить ID"
            check_result = "Название отличается"
            comment = "ID найден, но название поставщика плохо совпадает с названием в базе."
            action = "Проверить / заменить ID"
        else:
            decision = "ID верный"
            check_result = "Совпадает"
            comment = "ID найден, ID совпадает, название прошло проверку."
            action = "Оставить ID"
        rows.append({
            "Решение по ID": decision,
            "Схожесть, %": score,
            "ID в прайсе": oid,
            "Название поставщика": supplier_name,
            "ID в базе": db_id,
            "Название в базе": db_name,
            "Категория": excel_text(row.get("Категория", "")),
            "Поставщик": excel_text(row.get("Поставщик", "")),
            "Цена": row.get("Цена", ""),
            "Причина": reason,
            "Итог проверки": check_result,
            "Комментарий проверки": comment,
            "Что сделать": action,
            "URL в базе": str((product or {}).get("url", "") or "").strip(),
        })
    return pd.DataFrame(rows)
