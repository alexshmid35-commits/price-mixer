"""Payload builders for main consolidated data endpoints."""


def build_consolidated_table_rows(df, safe_json_value, delivery_days_from_row, row_category):
    rows = []
    for index, row in df.iterrows():
        rows.append([
            safe_json_value(row.get("OnlinerID", "")),
            safe_json_value(row.get("Название", "")),
            safe_json_value(row.get("Цена", 0)),
            safe_json_value(row.get("Поставщик", "")),
            safe_json_value(row.get("Гарантия", "")),
            delivery_days_from_row(row),
            safe_json_value(row.get("РРЦ", "")),
            safe_json_value(row.get("Цена без скидки", "")),
            int(index),
            safe_json_value(row_category(row)),
        ])
    return rows


def build_stats_payload(df, count_without_onliner_id, count_duplicate_onliner_id, export_row_count=None):
    return {
        "without_id": count_without_onliner_id(df),
        "duplicate_id_rows": count_duplicate_onliner_id(df),
        "export_rows": int(export_row_count or 0),
    }


def empty_stats_payload():
    return {"without_id": 0, "duplicate_id_rows": 0, "export_rows": 0}
